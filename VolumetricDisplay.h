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
#include <thread>
#include <vector>

// Define the maximum universes per layer
constexpr int MAX_UNIVERSES_PER_LAYER = 10;

class VolumetricDisplay {
public:
  VolumetricDisplay(int width, int height, int length, const std::string &ip,
                    int port, int universes_per_layer, float alpha);
  ~VolumetricDisplay();

  void run();
  void cleanup();

private:
  void setupOpenGL();
  void setupVBO();
  void listenArtNet();
  void updateColors();
  void render();
  void processInput(GLFWwindow *window);
  void windowCloseCallback(GLFWwindow *window);
  void mouseButtonCallback(GLFWwindow *window, int button, int action,
                           int mods);
  void cursorPositionCallback(GLFWwindow *window, double xpos, double ypos);
  void scrollCallback(GLFWwindow *window, double xoffset, double yoffset);
  void rotate(float angle, float x, float y, float z);
  void updateCamera();

  glm::vec3 camera_position;
  glm::quat camera_orientation;
  float camera_distance;
  bool left_mouse_button_pressed;
  bool right_mouse_button_pressed;
  double last_mouse_x;
  double last_mouse_y;

  int width, height, length;
  std::string ip;
  int port;
  int universes_per_layer;

  std::vector<std::array<unsigned char, 3>> pixels; // RGB for each voxel
  float alpha;
  std::atomic<bool> running;
  std::atomic<bool> needs_update;
  std::thread artnet_thread;

  GLuint vbo_vertices;
  GLuint vbo_colors;
  size_t vertex_count;
  GLuint vbo_indices;

  glm::mat4 rotation_matrix;
  glm::mat4 temp_matrix;

  boost::asio::io_service io_service;
  boost::asio::ip::udp::socket socket;
};

#endif // VOLUMETRIC_DISPLAY_H
