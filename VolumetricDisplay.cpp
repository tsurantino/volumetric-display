#include "VolumetricDisplay.h"
#include <boost/asio.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <iostream>

VolumetricDisplay::VolumetricDisplay(int width, int height, int length,
                                     const std::string &ip, int port,
                                     int universes_per_layer)
    : width(width), height(height), length(length), ip(ip), port(port),
      universes_per_layer(universes_per_layer),
      socket(io_service, boost::asio::ip::udp::endpoint(
                             boost::asio::ip::address::from_string(ip), port)) {

  if (universes_per_layer > MAX_UNIVERSES_PER_LAYER) {
    throw std::runtime_error("Layer size too large for ArtNet limitations");
  }

  pixels.resize(width * height * length, {0, 0, 0});

  running = true;
  needs_update = false;

  rotation_matrix = glm::mat4(1.0f);
  temp_matrix = glm::mat4(1.0f);

  artnet_thread = std::thread(&VolumetricDisplay::listenArtNet, this);
  setupOpenGL();
  setupVBO();
}

VolumetricDisplay::~VolumetricDisplay() { cleanup(); }

void VolumetricDisplay::setupOpenGL() {
  if (!glfwInit()) {
    throw std::runtime_error("Failed to initialize GLFW");
  }

  GLFWwindow *window =
      glfwCreateWindow(800, 600, "Volumetric Display", nullptr, nullptr);
  if (!window) {
    glfwTerminate();
    throw std::runtime_error("Failed to create GLFW window");
  }
  glfwMakeContextCurrent(window);
  glewInit();

  glEnable(GL_DEPTH_TEST);
  glEnable(GL_COLOR_MATERIAL);
  glEnable(GL_LIGHTING);
  glEnable(GL_LIGHT0);
  glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (GLfloat[]){1.0, 1.0, 1.0, 1.0});
}

void VolumetricDisplay::setupVBO() {
  std::vector<GLfloat> vertices;
  vertex_count = width * height * length * 24; // 24 vertices per voxel

  for (int x = 0; x < width; ++x) {
    for (int y = 0; y < height; ++y) {
      for (int z = 0; z < length; ++z) {
        // Define a small cube at each (x,y,z) position
        GLfloat size = 0.1f;
        vertices.insert(vertices.end(),
                        {x - size, y - size, z + size, x + size, y - size,
                         z + size, x + size, y + size, z + size, x - size,
                         y + size, z + size});
      }
    }
  }

  glGenBuffers(1, &vbo_vertices);
  glBindBuffer(GL_ARRAY_BUFFER, vbo_vertices);
  glBufferData(GL_ARRAY_BUFFER, vertices.size() * sizeof(GLfloat),
               vertices.data(), GL_STATIC_DRAW);
}

void VolumetricDisplay::listenArtNet() {
  while (running) {
    std::array<char, 1024> buffer;
    boost::asio::ip::udp::endpoint sender_endpoint;
    size_t length =
        socket.receive_from(boost::asio::buffer(buffer), sender_endpoint);

    if (strncmp(buffer.data(), "Art-Net", 7) != 0)
      continue;

    uint16_t opcode = ntohs(*reinterpret_cast<uint16_t *>(&buffer[8]));
    if (opcode == 0x5000) { // DMX Data
      uint16_t universe = ntohs(*reinterpret_cast<uint16_t *>(&buffer[14]));
      int layer = universe / universes_per_layer;
      int universe_in_layer = universe % universes_per_layer;
      int start_pixel = universe_in_layer * 170;

      for (int i = 0; i < 510 && (start_pixel + i / 3) < width * height;
           i += 3) {
        int idx = start_pixel + i / 3;
        int x = idx % width;
        int y = idx / width;
        pixels[x + y * width + layer * width * height] = {
            (unsigned char)buffer[18 + i], (unsigned char)buffer[18 + i + 1],
            (unsigned char)buffer[18 + i + 2]};
      }
    } else if (opcode == 0x5200) {
      needs_update = true;
    }
  }
}

void VolumetricDisplay::updateColors() {
  glBindBuffer(GL_ARRAY_BUFFER, vbo_colors);
  std::vector<GLfloat> colors;

  for (const auto &pixel : pixels) {
    GLfloat r = pixel[0] / 255.0f;
    GLfloat g = pixel[1] / 255.0f;
    GLfloat b = pixel[2] / 255.0f;
    for (int i = 0; i < 24; ++i) {
      colors.push_back(r);
      colors.push_back(g);
      colors.push_back(b);
    }
  }

  glBufferData(GL_ARRAY_BUFFER, colors.size() * sizeof(GLfloat), colors.data(),
               GL_DYNAMIC_DRAW);
}

void VolumetricDisplay::run() {
  while (running) {
    render();
    glfwPollEvents();
  }
}

void VolumetricDisplay::cleanup() {
  running = false;
  artnet_thread.join();
  socket.close();
  glfwTerminate();
}

void VolumetricDisplay::render() {
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

  glMatrixMode(GL_MODELVIEW);
  glLoadIdentity();
  glMultMatrixf(glm::value_ptr(rotation_matrix));

  glBindBuffer(GL_ARRAY_BUFFER, vbo_vertices);
  glVertexPointer(3, GL_FLOAT, 0, nullptr);
  glEnableClientState(GL_VERTEX_ARRAY);

  glBindBuffer(GL_ARRAY_BUFFER, vbo_colors);
  glColorPointer(3, GL_FLOAT, 0, nullptr);
  glEnableClientState(GL_COLOR_ARRAY);

  glDrawArrays(GL_QUADS, 0, vertex_count);

  glDisableClientState(GL_VERTEX_ARRAY);
  glDisableClientState(GL_COLOR_ARRAY);

  glfwSwapBuffers(glfwGetCurrentContext());
}
