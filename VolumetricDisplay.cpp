#include "VolumetricDisplay.h"
#include "absl/log/log.h"
#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <boost/asio.hpp>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "color_correction.h"

// Voxel Shaders
const char* vertex_shader_source = R"glsl(
    #version 330 core
    layout (location = 0) in vec3 aPos;
    layout (location = 1) in vec3 aInstancePosition;
    layout (location = 2) in vec4 aInstanceColor;

    out vec4 fColor;

    uniform mat4 model;
    uniform mat4 view;
    uniform mat4 projection;

    // Voxel scale is now 1.0, but we keep the uniform for flexibility.
    uniform float voxel_scale;

    void main()
    {
        // A voxel is a 1x1x1 cube centered at its instance position.
        vec3 scaled_pos = aPos * voxel_scale;
        gl_Position = projection * view * model * vec4(scaled_pos + aInstancePosition, 1.0);
        fColor = aInstanceColor;
    }
)glsl";

const char* fragment_shader_source = R"glsl(
    #version 330 core
    in vec4 fColor;
    out vec4 FragColor;

    void main()
    {
        if(fColor.a == 0.0)
            discard; // Discard transparent fragments
        FragColor = fColor;
    }
)glsl";

// Wireframe Shaders
const char* wireframe_vertex_shader_source = R"glsl(
    #version 330 core
    layout (location = 0) in vec3 aPos;
    uniform mat4 model;
    uniform mat4 view;
    uniform mat4 projection;
    void main()
    {
        gl_Position = projection * view * model * vec4(aPos, 1.0);
    }
)glsl";

const char* wireframe_fragment_shader_source = R"glsl(
    #version 330 core
    out vec4 FragColor;
    uniform vec3 color;
    void main()
    {
        FragColor = vec4(color, 1.0f);
    }
)glsl";

// Axis Shaders
const char* simple_vertex_shader_source = R"glsl(
    #version 330 core
    layout (location = 0) in vec3 aPos;
    layout (location = 1) in vec3 aColor;

    out vec3 fColor;

    uniform mat4 model;
    uniform mat4 view;
    uniform mat4 projection;

    void main()
    {
        gl_Position = projection * view * model * vec4(aPos, 1.0);
        fColor = aColor;
    }
)glsl";

const char* simple_fragment_shader_source = R"glsl(
    #version 330 core
    in vec3 fColor;
    out vec4 FragColor;

    void main()
    {
        FragColor = vec4(fColor, 1.0);
    }
)glsl";

VolumetricDisplay::VolumetricDisplay(int width, int height, int length,
                                     const std::string &ip, int port,
                                     int universes_per_layer, int layer_span,
                                     float alpha,
                                     const glm::vec3 &initial_rotation_rate, bool color_correction_enabled,
                                     const std::vector<glm::vec3>& cube_positions, float voxel_scale) // Add parameter
    : left_mouse_button_pressed(false), right_mouse_button_pressed(false),
      width(width), height(height), length(length), ip(ip), port(port),
      universes_per_layer(universes_per_layer), layer_span(layer_span),
      cube_positions(cube_positions),
      pixels(),
      alpha(alpha),
      voxel_scale(voxel_scale), // Initialize member
      running(false), show_axis(false),
      show_wireframe(false), needs_update(false),
      rotation_rate(initial_rotation_rate),
      color_correction_enabled_(color_correction_enabled) {

  if (universes_per_layer > MAX_UNIVERSES_PER_LAYER) {
    throw std::runtime_error("Layer size too large for ArtNet limitations");
  }

  size_t pixels_per_cube = width * height * (length / layer_span);
  pixels.resize(pixels_per_cube * cube_positions.size(), {0, 0, 0});

  running = true;
  rotation_matrix = glm::mat4(1.0f);
  temp_matrix = glm::mat4(1.0f);

  setupOpenGL();
  camera_position = glm::vec3(0.0f, 0.0f, 0.0f);

  glm::quat rot_x = glm::angleAxis(glm::radians(45.0f), glm::vec3(1.0f, 0.0f, 0.0f));
  glm::quat rot_y = glm::angleAxis(glm::radians(-35.0f), glm::vec3(0.0f, 1.0f, 0.0f));
  camera_orientation = rot_y * rot_x;
  camera_distance = std::max({(float)width, (float)height, (float)length}) * 3.0f;
  last_mouse_x = 0.0;
  last_mouse_y = 0.0;

  setupShaders();
  setupWireframeShader();
  setupAxesShader();
  setupVBO();

  for (size_t i = 0; i < cube_positions.size(); ++i) {
    int listen_port = port + i;
    auto socket = std::make_unique<boost::asio::ip::udp::socket>(io_service);
    socket->open(boost::asio::ip::udp::v4());
    socket->bind(boost::asio::ip::udp::endpoint(boost::asio::ip::address::from_string(ip), listen_port));
    sockets.push_back(std::move(socket));
    artnet_threads.emplace_back(&VolumetricDisplay::listenArtNet, this, i, listen_port);
  }
}

VolumetricDisplay::~VolumetricDisplay() { cleanup(); }

GLuint VolumetricDisplay::compileShader(GLenum type, const char* source) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, NULL);
    glCompileShader(shader);
    int success;
    char infoLog[512];
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (!success) {
        glGetShaderInfoLog(shader, 512, NULL, infoLog);
        LOG(FATAL) << "Shader compilation failed: " << infoLog;
    }
    return shader;
}

void VolumetricDisplay::setupShaders() {
    GLuint vertexShader = compileShader(GL_VERTEX_SHADER, vertex_shader_source);
    GLuint fragmentShader = compileShader(GL_FRAGMENT_SHADER, fragment_shader_source);
    shader_program = glCreateProgram();
    glAttachShader(shader_program, vertexShader);
    glAttachShader(shader_program, fragmentShader);
    glLinkProgram(shader_program);
    int success;
    glGetProgramiv(shader_program, GL_LINK_STATUS, &success);
    if (!success) {
        char infoLog[512];
        glGetProgramInfoLog(shader_program, 512, NULL, infoLog);
        LOG(FATAL) << "Shader linking failed: " << infoLog;
    }
    glDeleteShader(vertexShader);
    glDeleteShader(fragmentShader);
}

void VolumetricDisplay::setupWireframeShader() {
    GLuint vertexShader = compileShader(GL_VERTEX_SHADER, wireframe_vertex_shader_source);
    GLuint fragmentShader = compileShader(GL_FRAGMENT_SHADER, wireframe_fragment_shader_source);
    wireframe_shader_program = glCreateProgram();
    glAttachShader(wireframe_shader_program, vertexShader);
    glAttachShader(wireframe_shader_program, fragmentShader);
    glLinkProgram(wireframe_shader_program);
    int success;
    glGetProgramiv(wireframe_shader_program, GL_LINK_STATUS, &success);
    if (!success) {
        char infoLog[512];
        glGetProgramInfoLog(wireframe_shader_program, 512, NULL, infoLog);
        LOG(FATAL) << "Wireframe shader linking failed: " << infoLog;
    }
    glDeleteShader(vertexShader);
    glDeleteShader(fragmentShader);
}

void VolumetricDisplay::setupAxesShader() {
    GLuint vertexShader = compileShader(GL_VERTEX_SHADER, simple_vertex_shader_source);
    GLuint fragmentShader = compileShader(GL_FRAGMENT_SHADER, simple_fragment_shader_source);
    axis_shader_program = glCreateProgram();
    glAttachShader(axis_shader_program, vertexShader);
    glAttachShader(axis_shader_program, fragmentShader);
    glLinkProgram(axis_shader_program);
    int success;
    glGetProgramiv(axis_shader_program, GL_LINK_STATUS, &success);
    if (!success) {
        char infoLog[512];
        glGetProgramInfoLog(axis_shader_program, 512, NULL, infoLog);
        LOG(FATAL) << "Axis shader linking failed: " << infoLog;
    }
    glDeleteShader(vertexShader);
    glDeleteShader(fragmentShader);
}

void VolumetricDisplay::drawWireframeCubes() {
    glUseProgram(wireframe_shader_program);

    glm::mat4 view = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -camera_distance)) * glm::toMat4(camera_orientation);
    glm::mat4 projection = glm::perspective(glm::radians(45.0f), viewport_aspect, 0.1f, 500.0f);

    glUniformMatrix4fv(glGetUniformLocation(wireframe_shader_program, "view"), 1, GL_FALSE, glm::value_ptr(view));
    glUniformMatrix4fv(glGetUniformLocation(wireframe_shader_program, "projection"), 1, GL_FALSE, glm::value_ptr(projection));
    glUniform3f(glGetUniformLocation(wireframe_shader_program, "color"), 1.0f, 1.0f, 1.0f);

    glBindVertexArray(wireframe_vao);

    for (const auto& pos : cube_positions) {
        glm::mat4 scale_matrix = glm::scale(glm::mat4(1.0f), glm::vec3(width, height, length));
        glm::vec3 center_offset(width / 2.0f, height / 2.0f, length / 2.0f);
        glm::mat4 trans_matrix = glm::translate(glm::mat4(1.0f), pos + center_offset);

        glm::mat4 model = trans_matrix * scale_matrix;

        glUniformMatrix4fv(glGetUniformLocation(wireframe_shader_program, "model"), 1, GL_FALSE, glm::value_ptr(model));
        glDrawElements(GL_LINES, 24, GL_UNSIGNED_INT, 0);
    }
    glBindVertexArray(0);
}

void VolumetricDisplay::drawAxes() {
    glUseProgram(axis_shader_program);
    glLineWidth(2.0f);

    float axis_length = std::max({(float)width, (float)height, (float)length}) * 1.5f;
    glm::mat4 model = glm::scale(glm::mat4(1.0f), glm::vec3(axis_length));

    // **FIX**: Use the same view and projection matrices as everything else
    glm::mat4 view = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -camera_distance)) * glm::toMat4(camera_orientation);
    glm::mat4 projection = glm::perspective(glm::radians(45.0f), viewport_aspect, 0.1f, 500.0f);

    glUniformMatrix4fv(glGetUniformLocation(axis_shader_program, "model"), 1, GL_FALSE, glm::value_ptr(model));
    glUniformMatrix4fv(glGetUniformLocation(axis_shader_program, "view"), 1, GL_FALSE, glm::value_ptr(view));
    glUniformMatrix4fv(glGetUniformLocation(axis_shader_program, "projection"), 1, GL_FALSE, glm::value_ptr(projection));

    glBindVertexArray(axis_vao);
    glDrawArrays(GL_LINES, 0, 6);
    glBindVertexArray(0);
}

void VolumetricDisplay::setupOpenGL() {
  if (!glfwInit()) {
    throw std::runtime_error("Failed to initialize GLFW");
  }

  glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
  glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
  glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
#ifdef __APPLE__
  glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
#endif

  GLFWwindow *window =
      glfwCreateWindow(800, 800, "Volumetric Display", nullptr, nullptr);
  if (!window) {
    glfwTerminate();
    throw std::runtime_error("Failed to create GLFW window");
  }
  glfwMakeContextCurrent(window);
  glewExperimental = GL_TRUE;
  if (glewInit() != GLEW_OK) {
      throw std::runtime_error("Failed to initialize GLEW");
  }


  glfwSetWindowUserPointer(window, this);
  glfwSetWindowCloseCallback(window, [](GLFWwindow *window) {
    static_cast<VolumetricDisplay *>(glfwGetWindowUserPointer(window))
        ->windowCloseCallback(window);
  });
   glfwSetMouseButtonCallback(
      window, [](GLFWwindow *window, int button, int action, int mods) {
        static_cast<VolumetricDisplay *>(glfwGetWindowUserPointer(window))
            ->mouseButtonCallback(window, button, action, mods);
      });
  glfwSetCursorPosCallback(
      window, [](GLFWwindow *window, double xpos, double ypos) {
        static_cast<VolumetricDisplay *>(glfwGetWindowUserPointer(window))
            ->cursorPositionCallback(window, xpos, ypos);
      });
  glfwSetScrollCallback(
      window, [](GLFWwindow *window, double xoffset, double yoffset) {
        static_cast<VolumetricDisplay *>(glfwGetWindowUserPointer(window))
            ->scrollCallback(window, xoffset, yoffset);
      });

  glfwSetKeyCallback(window, [](GLFWwindow *window, int key, int scancode,
                                int action, int mods) {
    static_cast<VolumetricDisplay *>(glfwGetWindowUserPointer(window))
        ->keyCallback(window, key, scancode, action, mods);
  });

  glfwSetFramebufferSizeCallback(
      window, [](GLFWwindow *window, int width, int height) {
        static_cast<VolumetricDisplay *>(glfwGetWindowUserPointer(window))
            ->framebufferSizeCallback(window, width, height);
      });

  glfwGetFramebufferSize(window, &viewport_width, &viewport_height);
  glViewport(0, 0, viewport_width, viewport_height);
  viewport_aspect =
      static_cast<float>(viewport_width) / static_cast<float>(viewport_height);

  glEnable(GL_DEPTH_TEST);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
}

void VolumetricDisplay::setupVBO() {
    // VOXEL SETUP
    num_voxels = width * height * (length / layer_span) * cube_positions.size();

    GLfloat vertices[] = {
        -0.5f, -0.5f,  0.5f, 0.5f, -0.5f,  0.5f, 0.5f,  0.5f,  0.5f, -0.5f,  0.5f,  0.5f,
        -0.5f, -0.5f, -0.5f, 0.5f, -0.5f, -0.5f, 0.5f,  0.5f, -0.5f, -0.5f,  0.5f, -0.5f,
    };
    GLuint indices[] = {
        0, 1, 2, 2, 3, 0, 1, 5, 6, 6, 2, 1, 5, 4, 7, 7, 6, 5,
        4, 0, 3, 3, 7, 4, 3, 2, 6, 6, 7, 3, 4, 5, 1, 1, 0, 4
    };
    vertex_count = 36;

    std::vector<glm::vec3> instance_positions(num_voxels);
    size_t i = 0;
    for (const auto& cube_pos : cube_positions) {
        for (int z = 0; z < length; z += layer_span) {
            for (int y = 0; y < height; ++y) {
                for (int x = 0; x < width; ++x) {
                    if (i < num_voxels) {
                        // Voxel center is at (x + 0.5, y + 0.5, z + 0.5)
                        instance_positions[i++] = glm::vec3(x + 0.5f, y + 0.5f, z + 0.5f) + cube_pos;
                    }
                }
            }
        }
    }

    std::vector<glm::vec4> instance_colors(num_voxels, glm::vec4(0.0f, 0.0f, 0.0f, 0.0f)); // Use vec4 for RGBA

    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);

    glGenBuffers(1, &vbo_vertices);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_vertices);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(GLfloat), (void*)0);
    glEnableVertexAttribArray(0);

    glGenBuffers(1, &vbo_indices);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, vbo_indices);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(indices), indices, GL_STATIC_DRAW);

    glGenBuffers(1, &vbo_instance_positions);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_instance_positions);
    glBufferData(GL_ARRAY_BUFFER, num_voxels * sizeof(glm::vec3), &instance_positions[0], GL_STATIC_DRAW);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(glm::vec3), (void*)0);
    glEnableVertexAttribArray(1);
    glVertexAttribDivisor(1, 1);

    glGenBuffers(1, &vbo_instance_colors);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_instance_colors);
    glBufferData(GL_ARRAY_BUFFER, num_voxels * sizeof(glm::vec4), &instance_colors[0], GL_DYNAMIC_DRAW);
    glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(glm::vec4), (void*)0); // Changed size to 4
    glEnableVertexAttribArray(2);
    glVertexAttribDivisor(2, 1);

    // WIREFRAME SETUP
    GLfloat wireframe_vertices[] = {
        -0.5f, -0.5f, -0.5f,  0.5f, -0.5f, -0.5f,
         0.5f,  0.5f, -0.5f, -0.5f,  0.5f, -0.5f,
        -0.5f, -0.5f,  0.5f,  0.5f, -0.5f,  0.5f,
         0.5f,  0.5f,  0.5f, -0.5f,  0.5f,  0.5f,
    };

    GLuint wireframe_indices[] = {
        0, 1, 1, 2, 2, 3, 3, 0, // Bottom face
        4, 5, 5, 6, 6, 7, 7, 4, // Top face
        0, 4, 1, 5, 2, 6, 3, 7  // Connecting lines
    };

    glGenVertexArrays(1, &wireframe_vao);
    glBindVertexArray(wireframe_vao);

    glGenBuffers(1, &wireframe_vbo);
    glBindBuffer(GL_ARRAY_BUFFER, wireframe_vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(wireframe_vertices), wireframe_vertices, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(GLfloat), (void*)0);
    glEnableVertexAttribArray(0);

    glGenBuffers(1, &wireframe_ebo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, wireframe_ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(wireframe_indices), wireframe_indices, GL_STATIC_DRAW);

    // AXES SETUP
    GLfloat axis_vertices[] = {
        // Position      // Color
        0.0f, 0.0f, 0.0f,  1.0f, 0.0f, 0.0f, // X-axis Start (Red)
        1.0f, 0.0f, 0.0f,  1.0f, 0.0f, 0.0f, // X-axis End

        0.0f, 0.0f, 0.0f,  0.0f, 1.0f, 0.0f, // Y-axis Start (Green)
        0.0f, 1.0f, 0.0f,  0.0f, 1.0f, 0.0f, // Y-axis End

        0.0f, 0.0f, 0.0f,  0.0f, 0.0f, 1.0f, // Z-axis Start (Blue)
        0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f, // Z-axis End
    };

    glGenVertexArrays(1, &axis_vao);
    glGenBuffers(1, &axis_vbo);

    glBindVertexArray(axis_vao);
    glBindBuffer(GL_ARRAY_BUFFER, axis_vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(axis_vertices), axis_vertices, GL_STATIC_DRAW);

    // Position attribute
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(GLfloat), (void*)0);
    glEnableVertexAttribArray(0);
    // Color attribute
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(GLfloat), (void*)(3* sizeof(GLfloat)));
    glEnableVertexAttribArray(1);

    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindVertexArray(0);
}

void VolumetricDisplay::listenArtNet(int cube_index, int listen_port) {
  LOG(INFO) << "Listening for Art-Net for cube " << cube_index << " on " << ip << ":" << listen_port;
  size_t pixels_per_cube = width * height * (length / layer_span);
  size_t pixel_buffer_offset = cube_index * pixels_per_cube;

  while (running) {
    std::array<char, 1024> buffer;
    boost::asio::ip::udp::endpoint sender_endpoint;
    boost::system::error_code ec;

    size_t total_length = sockets[cube_index]->receive_from(boost::asio::buffer(buffer),
                                              sender_endpoint, 0, ec);

    if (ec == boost::asio::error::operation_aborted) {
      break;
    } else if (ec) {
      if (!running) break;
      LOG(ERROR) << "Error receiving data on port " << listen_port << ": " << ec.message();
      break;
    }

    if (total_length < 18) continue;

    if (strncmp(buffer.data(), "Art-Net\0", 8) != 0) continue;

    uint16_t opcode = *reinterpret_cast<uint16_t *>(&buffer[8]);

    if (opcode == 0x5000) { // DMX Data
      uint16_t universe = *reinterpret_cast<uint16_t *>(&buffer[14]);
      uint16_t length = ntohs(*reinterpret_cast<uint16_t *>(&buffer[16]));

      int layer = universe / universes_per_layer;
      int universe_in_layer = universe % universes_per_layer;
      int start_pixel = universe_in_layer * (512 / 3);

      auto lg = std::lock_guard(pixels_mu);
      for (size_t i = 0; i < length; i += 3) {
        int idx = start_pixel + i / 3;
        int x = idx % width;
        int y = idx / width;
        size_t pixel_index =
            pixel_buffer_offset + static_cast<size_t>(x + y * width + layer * width * height);
        if (pixel_index < pixels.size()) {
          pixels[pixel_index] = {(unsigned char)buffer[18 + i],
                               (unsigned char)buffer[18 + i + 1],
                               (unsigned char)buffer[18 + i + 2]};
        }
      }
      view_update.notify_all();
    }
  }
}

void VolumetricDisplay::updateColors() {
    // This is the performance fix. We no longer wait for the network thread.
    // We just lock briefly to copy the data.
    auto lg = std::lock_guard(pixels_mu);

    std::vector<glm::vec4> instance_colors(num_voxels);

    for (size_t i = 0; i < num_voxels; ++i) {
        auto pixel = pixels[i]; // Make a copy
        if (color_correction_enabled_) {
            color_corrector_.ReverseCorrectInPlace(pixel.data());
        }

        float r = pixel[0] / 255.0f;
        float g = pixel[1] / 255.0f;
        float b = pixel[2] / 255.0f;

        float current_alpha = (r == 0.0f && g == 0.0f && b == 0.0f) ? 0.0f : alpha;

        instance_colors[i] = glm::vec4(r, g, b, current_alpha);
    }

    glBindBuffer(GL_ARRAY_BUFFER, vbo_instance_colors);
    glBufferSubData(GL_ARRAY_BUFFER, 0, num_voxels * sizeof(glm::vec4), &instance_colors[0]);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void VolumetricDisplay::run() {
  while (running && !glfwWindowShouldClose(glfwGetCurrentContext())) {
    render();
    glfwPollEvents();
  }
}

void VolumetricDisplay::cleanup() {
  running = false;
  io_service.stop();
  for (auto& socket : sockets) {
      if (socket && socket->is_open()) {
          socket->close();
      }
  }
  for (auto& thread : artnet_threads) {
      if (thread.joinable()) {
          thread.join();
      }
  }

  glDeleteVertexArrays(1, &vao);
  glDeleteBuffers(1, &vbo_vertices);
  glDeleteBuffers(1, &vbo_indices);
  glDeleteBuffers(1, &vbo_instance_positions);
  glDeleteBuffers(1, &vbo_instance_colors);
  glDeleteProgram(shader_program);

  glDeleteVertexArrays(1, &wireframe_vao);
  glDeleteBuffers(1, &wireframe_vbo);
  glDeleteBuffers(1, &wireframe_ebo);
  glDeleteProgram(wireframe_shader_program);

  glfwTerminate();
}

void VolumetricDisplay::framebufferSizeCallback(GLFWwindow *window, int width,
                                                int height) {
  glViewport(0, 0, width, height);
  viewport_width = width;
  viewport_height = height;
  viewport_aspect =
      static_cast<float>(viewport_width) / static_cast<float>(viewport_height);

  view_update.notify_all();
}

void VolumetricDisplay::updateCamera() {
    // This logic is now handled inside the render loop with projection and view matrices
}

void VolumetricDisplay::render() {
  double current_time = glfwGetTime();
  double delta_time = current_time - last_frame_time;
  last_frame_time = current_time;

  if (glm::length(rotation_rate) > 0.0f) {
    float angle_x = glm::radians(rotation_rate.x * static_cast<float>(delta_time));
    float angle_y = glm::radians(rotation_rate.y * static_cast<float>(delta_time));
    float angle_z = glm::radians(rotation_rate.z * static_cast<float>(delta_time));
    glm::quat rot_x = glm::angleAxis(angle_x, glm::vec3(1.0f, 0.0f, 0.0f));
    glm::quat rot_y = glm::angleAxis(angle_y, glm::vec3(0.0f, 1.0f, 0.0f));
    glm::quat rot_z = glm::angleAxis(angle_z, glm::vec3(0.0f, 0.0f, 1.0f));
    camera_orientation = rot_y * rot_x * rot_z * camera_orientation;
    camera_orientation = glm::normalize(camera_orientation);
  }

  updateColors();

  glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

  // Define View and Projection matrices once for all rendering
  glm::mat4 view = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -camera_distance)) * glm::toMat4(camera_orientation);
  glm::mat4 projection = glm::perspective(glm::radians(45.0f), viewport_aspect, 0.1f, 500.0f);

  // Draw the voxels
  glUseProgram(shader_program);
  glUniform1f(glGetUniformLocation(shader_program, "voxel_scale"), this->voxel_scale);
  glm::mat4 model = glm::mat4(1.0f);
  glUniformMatrix4fv(glGetUniformLocation(shader_program, "model"), 1, GL_FALSE, glm::value_ptr(model));
  glUniformMatrix4fv(glGetUniformLocation(shader_program, "view"), 1, GL_FALSE, glm::value_ptr(view));
  glUniformMatrix4fv(glGetUniformLocation(shader_program, "projection"), 1, GL_FALSE, glm::value_ptr(projection));

  glBindVertexArray(vao);
  glDrawElementsInstanced(GL_TRIANGLES, vertex_count, GL_UNSIGNED_INT, 0, num_voxels);
  glBindVertexArray(0);

  if (show_wireframe) {
      drawWireframeCubes();
  }
  if (show_axis) {
      drawAxes();
  }

  glfwSwapBuffers(glfwGetCurrentContext());
}

void VolumetricDisplay::keyCallback(GLFWwindow *window, int key, int scancode,
                                    int action, int mods) {
  if (key == GLFW_KEY_A && action == GLFW_PRESS) {
    show_axis = !show_axis;
  }

  if (key == GLFW_KEY_B && action == GLFW_PRESS) {
    show_wireframe = !show_wireframe;
  }

  view_update.notify_all();
}

void VolumetricDisplay::rotate(float angle, float x, float y, float z) {
  glm::vec3 axis = glm::normalize(glm::vec3(x, y, z));
  glm::quat rotation = glm::angleAxis(glm::radians(angle), axis);
  camera_orientation = rotation * camera_orientation;
}

void VolumetricDisplay::windowCloseCallback(GLFWwindow *window) {
  VLOG(0) << "Window closed";
  running = false;
  view_update.notify_all();
}

void VolumetricDisplay::mouseButtonCallback(GLFWwindow *window, int button,
                                            int action, int mods) {
  if (button == GLFW_MOUSE_BUTTON_LEFT) {
      if (action == GLFW_PRESS) {
          left_mouse_button_pressed = true;
          glfwGetCursorPos(window, &last_mouse_x, &last_mouse_y);
      } else if (action == GLFW_RELEASE) {
          left_mouse_button_pressed = false;
      }
  }
}

void VolumetricDisplay::cursorPositionCallback(GLFWwindow *window, double xpos,
                                               double ypos) {
  if (left_mouse_button_pressed) {
    float dx = static_cast<float>(xpos - last_mouse_x);
    float dy = static_cast<float>(ypos - last_mouse_y);

    glm::quat rot_x = glm::angleAxis(glm::radians(dy * 0.2f), glm::vec3(1.0f, 0.0f, 0.0f));
    glm::quat rot_y = glm::angleAxis(glm::radians(dx * 0.2f), glm::vec3(0.0f, 1.0f, 0.0f));

    camera_orientation = rot_y * rot_x * camera_orientation;
  }
  last_mouse_x = xpos;
  last_mouse_y = ypos;

  view_update.notify_all();
}

void VolumetricDisplay::scrollCallback(GLFWwindow *window, double xoffset,
                                       double yoffset) {
  camera_distance -= static_cast<float>(yoffset) * 2.0f;
  if (camera_distance < 1.0f) {
    camera_distance = 1.0f;
  }

  view_update.notify_all();
}
