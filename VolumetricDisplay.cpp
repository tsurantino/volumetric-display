#include "VolumetricDisplay.h"
#include "nlohmann/json.hpp"
#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <boost/asio.hpp>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <cmath>

using json = nlohmann::json;

// ArtNet packet constants
constexpr int ARTNET_HEADER_SIZE = 18;
constexpr int ARTNET_OPCODE_OFFSET = 8;
constexpr int ARTNET_UNIVERSE_OFFSET = 14;
constexpr int ARTNET_LENGTH_OFFSET = 16;
constexpr unsigned short ARTNET_OPCODE_DMX = 0x5000;
constexpr int PIXELS_PER_UNIVERSE = 170; // 510 channels / 3 colors per pixel

VolumetricDisplay::VolumetricDisplay(const std::string& config_path, float alpha, const glm::vec3& initial_rotation_rate, bool color_correction_enabled)
    : color_corrector_(util::kColorCorrectorWs2812bOptions) {
    this->alpha = alpha;
    this->rotation_rate = initial_rotation_rate;
    this->color_correction_enabled_ = color_correction_enabled;
    this->running = true;
    this->needs_update = false;
    this->show_axis = true;
    this->show_wireframe = true;
    this->left_mouse_button_pressed = false;
    this->right_mouse_button_pressed = false;
    this->last_mouse_x = 0.0;
    this->last_mouse_y = 0.0;
    
    std::ifstream f(config_path);
    if (!f.is_open()) throw std::runtime_error("Failed to open config file: " + config_path);
    json config = json::parse(f);

    sscanf(config["cube_geometry"].get<std::string>().c_str(), "%dx%dx%d", &cube_width, &cube_height, &cube_length);

    if (config.contains("orientation")) config.at("orientation").get_to(orientation);
    else orientation = {"X", "Y", "Z"};
    
    // --- NEW: Calculate constants for auto-generation ---
    const int PIXELS_PER_LAYER = cube_width * cube_height;
    const int UNIVERSES_PER_LAYER = (PIXELS_PER_LAYER + PIXELS_PER_UNIVERSE - 1) / PIXELS_PER_UNIVERSE; // Integer ceil division
    const int UNIVERSES_PER_CUBE = cube_length * UNIVERSES_PER_LAYER;
    
    json defaults = config.value("defaults", json::object());
    int default_port = defaults.value("port", 6454);

    int max_x = 0, max_y = 0, max_z = 0;
    int cube_index = 0;
    for (const auto& cube_config : config["cubes"]) {
        Cube c;
        c.id = cubes.size();
        c.width = cube_width; c.height = cube_height; c.length = cube_length;
        c.position = {cube_config["position"][0], cube_config["position"][1], cube_config["position"][2]};
        c.pixels.resize(c.width * c.height * c.length, {0, 0, 0});
        
        max_x = std::max(max_x, c.position.x);
        max_y = std::max(max_y, c.position.y);
        max_z = std::max(max_z, c.position.z);
        
        // --- NEW: Auto-generate mapping if it doesn't exist ---
        if (cube_config.contains("z_mapping")) {
            // Use existing explicit definition
            for (const auto& mapping : cube_config["z_mapping"]) {
                int port = mapping.value("port", default_port);
                int base_universe = mapping.value("base_universe", 0);
                int universes_per_layer_explicit = mapping.value("universes_per_layer", 1);
                const auto& z_indices = mapping["z_indices"].get<std::vector<int>>();
                
                if (port_to_socket_index.find(port) == port_to_socket_index.end()) {
                    port_to_socket_index[port] = sockets.size();
                    sockets.emplace_back(std::make_unique<boost::asio::ip::udp::socket>(io_service, boost::asio::ip::udp::endpoint(boost::asio::ip::udp::v4(), port)));
                }

                for (size_t i = 0; i < z_indices.size(); ++i) {
                    for (int j = 0; j < universes_per_layer_explicit; ++j) {
                        int universe = base_universe + (i * universes_per_layer_explicit) + j;
                        universe_to_target_map[universe] = {c.id, z_indices[i], j * PIXELS_PER_UNIVERSE};
                    }
                }
            }
        } else {
            // Generate mapping programmatically
            int port = default_port;
            int base_universe = cube_index * UNIVERSES_PER_CUBE;

            if (port_to_socket_index.find(port) == port_to_socket_index.end()) {
                port_to_socket_index[port] = sockets.size();
                sockets.emplace_back(std::make_unique<boost::asio::ip::udp::socket>(io_service, boost::asio::ip::udp::endpoint(boost::asio::ip::udp::v4(), port)));
            }

            for (int z = 0; z < c.length; ++z) { // z is the layer index
                for (int u = 0; u < UNIVERSES_PER_LAYER; ++u) { // u is the universe index within the layer
                    int universe = base_universe + (z * UNIVERSES_PER_LAYER) + u;
                    universe_to_target_map[universe] = {c.id, z, u * PIXELS_PER_UNIVERSE};
                }
            }
        }
        cubes.push_back(std::move(c));
        cube_index++;
    }

    grid_width = max_x + 1; grid_height = max_y + 1; grid_length = max_z + 1;
    total_dimensions = { (float)(grid_width * cube_width), (float)(grid_height * cube_height), (float)(grid_length * cube_length) };

    setupOpenGL();
    camera_distance = glm::length(total_dimensions) * 1.5f;
    camera_orientation = glm::quat(1.0f, 0.0f, 0.0f, 0.0f);
    setupVBOs();

    for (size_t i = 0; i < sockets.size(); ++i) {
        artnet_threads.emplace_back(&VolumetricDisplay::listenArtNet, this, i);
    }
}

VolumetricDisplay::~VolumetricDisplay() {
    cleanup();
}

void VolumetricDisplay::run() {
    last_frame_time = glfwGetTime();
    while (running && !glfwWindowShouldClose(window)) {
        glfwPollEvents();
        updateColors();
        render();
        glfwSwapBuffers(window);
    }
}

void VolumetricDisplay::cleanup() {
    running = false;
    io_service.stop();
    for (auto& thread : artnet_threads) if (thread.joinable()) thread.join();
    
    // Delete the consolidated buffers
    glDeleteBuffers(1, &vbo_all_vertices_);
    glDeleteBuffers(1, &vbo_all_colors_);

    if (window) glfwDestroyWindow(window);
    glfwTerminate();
}

void VolumetricDisplay::listenArtNet(int socket_index) {
    auto& socket = *sockets[socket_index];
    std::vector<unsigned char> recv_buffer(1024);
    boost::asio::ip::udp::endpoint remote_endpoint;

    while (running) {
        boost::system::error_code error;
        size_t len = socket.receive_from(boost::asio::buffer(recv_buffer), remote_endpoint, 0, error);
        if (error || !running) break;
        if (len < ARTNET_HEADER_SIZE) continue;

        if (memcmp(recv_buffer.data(), "Art-Net\0", 8) == 0 && *reinterpret_cast<uint16_t*>(&recv_buffer[ARTNET_OPCODE_OFFSET]) == ARTNET_OPCODE_DMX) {
            uint16_t universe = *reinterpret_cast<uint16_t*>(&recv_buffer[ARTNET_UNIVERSE_OFFSET]);
            uint16_t length = (recv_buffer[ARTNET_LENGTH_OFFSET] << 8) | recv_buffer[ARTNET_LENGTH_OFFSET + 1];

            if (universe_to_target_map.count(universe)) {
                const auto& target = universe_to_target_map.at(universe);
                Cube& target_cube = cubes.at(target.cube_id);
                std::lock_guard<std::mutex> lock(pixels_mu);
                
                int z_offset = target.z_slice * target_cube.width * target_cube.height;
                for (size_t i = 0; i < length; i += 3) {
                    int pixel_in_layer = target.pixel_offset + (i / 3);
                    if (pixel_in_layer >= target_cube.width * target_cube.height) continue;
                    
                    size_t pixel_index = z_offset + pixel_in_layer;
                    if (pixel_index >= target_cube.pixels.size()) continue;

                    target_cube.pixels[pixel_index] = {recv_buffer[ARTNET_HEADER_SIZE + i], recv_buffer[ARTNET_HEADER_SIZE + i + 1], recv_buffer[ARTNET_HEADER_SIZE + i + 2]};
                }
                needs_update = true;
            }
        }
    }
}

void VolumetricDisplay::updateColors() {
    if (!needs_update) return;
    std::lock_guard<std::mutex> lock(pixels_mu);
    
    glBindBuffer(GL_ARRAY_BUFFER, vbo_all_colors_);
    for (const auto& cube : cubes) {
        std::vector<GLfloat> color_data;
        color_data.reserve(cube.pixels.size() * 4);
        for (const auto& pixel : cube.pixels) {
            std::array<unsigned char, 3> corrected_pixel = pixel;
            if (color_correction_enabled_) {
                color_corrector_.ReverseCorrectInPlace(corrected_pixel.data());
            }
            color_data.push_back(corrected_pixel[0] / 255.0f);
            color_data.push_back(corrected_pixel[1] / 255.0f);
            color_data.push_back(corrected_pixel[2] / 255.0f);
            color_data.push_back(alpha);
        }
        // Update only the relevant slice of the large buffer
        glBufferSubData(GL_ARRAY_BUFFER, cube.vertex_offset * 4 * sizeof(GLfloat), color_data.size() * sizeof(GLfloat), color_data.data());
    }
    needs_update = false;
}

void VolumetricDisplay::setupVBOs() {
    std::vector<GLfloat> all_vertices;
    std::vector<GLfloat> all_colors;
    size_t current_offset = 0;

    for (auto& cube : cubes) {
        cube.vertex_offset = current_offset;
        std::vector<GLfloat> cube_vertices;

        for (int z = 0; z < cube.length; ++z) {
            for (int y = 0; y < cube.height; ++y) {
                for (int x = 0; x < cube.width; ++x) {
                    cube_vertices.push_back(static_cast<float>(x));
                    cube_vertices.push_back(static_cast<float>(y));
                    cube_vertices.push_back(static_cast<float>(z));
                    all_colors.insert(all_colors.end(), {0.0f, 0.0f, 0.0f, alpha});
                }
            }
        }
        cube.vertex_count = cube_vertices.size() / 3;
        all_vertices.insert(all_vertices.end(), cube_vertices.begin(), cube_vertices.end());
        current_offset += cube.vertex_count;
    }

    glGenBuffers(1, &vbo_all_vertices_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_all_vertices_);
    glBufferData(GL_ARRAY_BUFFER, all_vertices.size() * sizeof(GLfloat), all_vertices.data(), GL_STATIC_DRAW);

    glGenBuffers(1, &vbo_all_colors_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_all_colors_);
    glBufferData(GL_ARRAY_BUFFER, all_colors.size() * sizeof(GLfloat), all_colors.data(), GL_DYNAMIC_DRAW);
}

void VolumetricDisplay::render() {
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glfwGetFramebufferSize(window, &viewport_width, &viewport_height);
    viewport_aspect = (float)viewport_width / (float)viewport_height;
    glm::mat4 projection = glm::perspective(glm::radians(45.0f), viewport_aspect, 0.1f, 1000.0f);
    glLoadMatrixf(glm::value_ptr(projection));

    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    updateCamera();
    
    // --- START: Corrected Transformation Logic ---

    // 1. Center the entire grid of cubes in front of the camera.
    glTranslatef(-total_dimensions.x / 2.0f, -total_dimensions.y / 2.0f, -total_dimensions.z / 2.0f);

    // 2. Apply a single orientation rotation to the whole world space.
    // This ensures all cubes are oriented the same way relative to each other.
    if(orientation[0] == "-Z" && orientation[1] == "Y" && orientation[2] == "X") {
        glRotatef(-90.0f, 0.0f, 1.0f, 0.0f); // Rotate the entire grid
    }
    // Add other `else if` cases for different orientations here if needed.

    glEnableClientState(GL_VERTEX_ARRAY);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_all_vertices_);
    glVertexPointer(3, GL_FLOAT, 0, nullptr);

    glEnableClientState(GL_COLOR_ARRAY);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_all_colors_);
    glColorPointer(4, GL_FLOAT, 0, nullptr);

    // 3. Loop through each cube and draw it at its grid position.
    for (const auto& cube : cubes) {
        glPushMatrix();
        glTranslatef(cube.position.x * cube.width, cube.position.y * cube.height, cube.position.z * cube.length);
        
        glPointSize(2.0f);
        glDrawArrays(GL_POINTS, cube.vertex_offset, cube.vertex_count);
        
        if (show_wireframe) {
            drawWireframeCube(cube);
        }
        
        glPopMatrix();
    }
    
    glDisableClientState(GL_COLOR_ARRAY);
    glDisableClientState(GL_VERTEX_ARRAY);

    if (show_axis) {
        // Draw axes at the world origin for reference
        glLineWidth(2.0f);
        glBegin(GL_LINES);
        // X-axis in Red
        glColor3f(1.0f, 0.0f, 0.0f); glVertex3f(0,0,0); glVertex3f(10, 0, 0);
        // Y-axis in Green
        glColor3f(0.0f, 1.0f, 0.0f); glVertex3f(0,0,0); glVertex3f(0, 10, 0);
        // Z-axis in Blue
        glColor3f(0.0f, 0.0f, 1.0f); glVertex3f(0,0,0); glVertex3f(0, 0, 10);
        glEnd();
    }
}

void VolumetricDisplay::updateCamera() {
    glm::mat4 view = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -camera_distance));
    view *= glm::mat4_cast(camera_orientation);
    glLoadMatrixf(glm::value_ptr(view));
}

void VolumetricDisplay::drawWireframeCube(const Cube& cube) {
    glColor4f(0.5f, 0.5f, 0.5f, 0.3f);
    glLineWidth(1.0f);
    float w = cube.width -1, h = cube.height -1, l = cube.length -1;
    glm::vec3 p[8] = { {0,0,0}, {w,0,0}, {w,h,0}, {0,h,0}, {0,0,l}, {w,0,l}, {w,h,l}, {0,h,l} };
    int indices[] = { 0,1, 1,2, 2,3, 3,0, 4,5, 5,6, 6,7, 7,4, 0,4, 1,5, 2,6, 3,7 };
    glBegin(GL_LINES);
    for(int i = 0; i < 24; ++i) glVertex3fv(glm::value_ptr(p[indices[i]]));
    glEnd();
}

// --- GLFW Setup and Callbacks (Unchanged from previous correct version) ---
void VolumetricDisplay::setupOpenGL() {
    if (!glfwInit()) throw std::runtime_error("Failed to initialize GLFW");
    int window_width = 800, window_height = 800;
    window = glfwCreateWindow(window_width, window_height, "Volumetric Display", NULL, NULL);
    if (!window) {
        glfwTerminate();
        throw std::runtime_error("Failed to create GLFW window");
    }
    glfwMakeContextCurrent(window);
    glfwSetWindowUserPointer(window, this);

    glfwSetKeyCallback(window, [](GLFWwindow* w, int k, int s, int a, int m){ static_cast<VolumetricDisplay*>(glfwGetWindowUserPointer(w))->keyCallback(w, k, s, a, m); });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int b, int a, int m){ static_cast<VolumetricDisplay*>(glfwGetWindowUserPointer(w))->mouseButtonCallback(w, b, a, m); });
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y){ static_cast<VolumetricDisplay*>(glfwGetWindowUserPointer(w))->cursorPositionCallback(w, x, y); });
    glfwSetScrollCallback(window, [](GLFWwindow* w, double x, double y){ static_cast<VolumetricDisplay*>(glfwGetWindowUserPointer(w))->scrollCallback(w, x, y); });
    
    if (glewInit() != GLEW_OK) throw std::runtime_error("Failed to initialize GLEW");

    glEnable(GL_DEPTH_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glEnable(GL_PROGRAM_POINT_SIZE);
}

void VolumetricDisplay::processInput(GLFWwindow* window) {
    if (glfwGetKey(window, GLFW_KEY_ESCAPE) == GLFW_PRESS) running = false;
}

void VolumetricDisplay::keyCallback(GLFWwindow* window, int key, int scancode, int action, int mods) {
     if (action == GLFW_PRESS) {
        if (key == GLFW_KEY_A) show_axis = !show_axis;
        if (key == GLFW_KEY_W) show_wireframe = !show_wireframe;
        if (key == GLFW_KEY_R) camera_orientation = glm::quat(1.0f, 0.0f, 0.0f, 0.0f);
    }
}

void VolumetricDisplay::mouseButtonCallback(GLFWwindow* window, int button, int action, int mods) {
    if (button == GLFW_MOUSE_BUTTON_LEFT) {
        if (action == GLFW_PRESS) {
            left_mouse_button_pressed = true;
            glfwGetCursorPos(window, &last_mouse_x, &last_mouse_y);
        } else if (action == GLFW_RELEASE) {
            left_mouse_button_pressed = false;
        }
    }
}

void VolumetricDisplay::cursorPositionCallback(GLFWwindow* window, double xpos, double ypos) {
    if (left_mouse_button_pressed) {
        float deltaX = static_cast<float>(xpos - last_mouse_x);
        float deltaY = static_cast<float>(ypos - last_mouse_y);
        glm::quat rotX = glm::angleAxis(glm::radians(deltaY * 0.5f), glm::vec3(1.0f, 0.0f, 0.0f));
        glm::quat rotY = glm::angleAxis(glm::radians(deltaX * 0.5f), glm::vec3(0.0f, 1.0f, 0.0f));
        camera_orientation = rotY * rotX * camera_orientation;
        last_mouse_x = xpos;
        last_mouse_y = ypos;
    }
}

void VolumetricDisplay::scrollCallback(GLFWwindow* window, double xoffset, double yoffset) {
    camera_distance -= static_cast<float>(yoffset) * (glm::length(total_dimensions) * 0.05f);
    camera_distance = std::max(0.1f, camera_distance);
}

void VolumetricDisplay::framebufferSizeCallback(GLFWwindow* window, int width, int height) {
    glViewport(0, 0, width, height);
}