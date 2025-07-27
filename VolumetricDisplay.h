#ifndef VOLUMETRIC_DISPLAY_H
#define VOLUMETRIC_DISPLAY_H

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <array>
#include <atomic>
#include <boost/asio.hpp>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>
#include <mutex>
#include <thread>
#include <vector>
#include <string>
#include <map>
#include <condition_variable>

#include "color_correction.h"

struct Cube {
    int id;
    int width, height, length;
    glm::ivec3 position;
    std::vector<std::array<unsigned char, 3>> pixels;

    size_t vertex_offset;
    size_t vertex_count;
};

struct TargetVoxelInfo {
    int cube_id;
    int z_slice;
    int pixel_offset;
};

class VolumetricDisplay {
public:
    VolumetricDisplay(const std::string& config_path, float alpha, const glm::vec3& initial_rotation_rate, bool color_correction_enabled);
    ~VolumetricDisplay();
    void run();

private:
    void cleanup();
    void setupOpenGL();
    void setupVBOs();
    void listenArtNet(int socket_index);
    void updateColors();
    void render();
    void processInput(GLFWwindow* window);
    void mouseButtonCallback(GLFWwindow* window, int button, int action, int mods);
    void cursorPositionCallback(GLFWwindow* window, double xpos, double ypos);
    void scrollCallback(GLFWwindow* window, double xoffset, double yoffset);
    void keyCallback(GLFWwindow* window, int key, int scancode, int action, int mods);
    void framebufferSizeCallback(GLFWwindow* window, int width, int height);
    void updateCamera();
    void drawWireframeCube(const Cube& cube);

    GLFWwindow* window;
    glm::vec3 camera_position;
    glm::quat camera_orientation;
    float camera_distance;
    bool left_mouse_button_pressed;
    bool right_mouse_button_pressed;
    double last_mouse_x, last_mouse_y;
    double last_frame_time;
    int viewport_width, viewport_height;
    float viewport_aspect;
    std::mutex pixels_mu;
    std::condition_variable view_update;
    float alpha;
    std::atomic<bool> running;
    bool show_axis;
    bool show_wireframe;
    std::atomic<bool> needs_update;
    std::vector<std::thread> artnet_threads;
    std::vector<Cube> cubes;
    glm::vec3 rotation_rate;
    boost::asio::io_service io_service;
    std::vector<std::unique_ptr<boost::asio::ip::udp::socket>> sockets;
    std::map<int, int> port_to_socket_index;
    std::map<int, TargetVoxelInfo> universe_to_target_map;
    bool color_correction_enabled_;
    util::ReverseColorCorrector<3> color_corrector_;
    int cube_width, cube_height, cube_length;
    int grid_width, grid_height, grid_length;
    glm::vec3 total_dimensions;
    GLuint vbo_all_vertices_ = 0;
    GLuint vbo_all_colors_ = 0;
    std::vector<std::string> orientation;
};

#endif // VOLUMETRIC_DISPLAY_H