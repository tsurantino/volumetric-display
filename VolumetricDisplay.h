#ifndef VOLUMETRIC_DISPLAY_H
#define VOLUMETRIC_DISPLAY_H

#include <vector>
#include <array>
#include <thread>
#include <atomic>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <boost/asio.hpp>
#include <GL/glew.h>
#include <GLFW/glfw3.h>

// Define the maximum universes per layer
constexpr int MAX_UNIVERSES_PER_LAYER = 10;

class VolumetricDisplay {
public:
    VolumetricDisplay(int width, int height, int length, const std::string& ip, int port, int universes_per_layer);
    ~VolumetricDisplay();

    void run();
    void cleanup();

private:
    void setupOpenGL();
    void setupVBO();
    void listenArtNet();
    void updateColors();
    void render();
    void processInput(GLFWwindow* window);
    void rotate(float angle, float x, float y, float z);

    int width, height, length;
    std::string ip;
    int port;
    int universes_per_layer;

    std::vector<std::array<unsigned char, 3>> pixels; // RGB for each voxel
    std::atomic<bool> running;
    std::atomic<bool> needs_update;
    std::thread artnet_thread;

    GLuint vbo_vertices;
    GLuint vbo_colors;
    size_t vertex_count;

    glm::mat4 rotation_matrix;
    glm::mat4 temp_matrix;

    boost::asio::io_service io_service;
    boost::asio::ip::udp::socket socket;
};

#endif // VOLUMETRIC_DISPLAY_H
