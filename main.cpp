#include "VolumetricDisplay.h"
#include "absl/flags/flag.h"
#include "absl/flags/parse.h"
#include <iostream>

// Define command-line flags using Abseil
ABSL_FLAG(std::string, geometry, "16x16x16",
          "Width, height, and length of the display");
ABSL_FLAG(std::string, ip, "127.0.0.1",
          "IP address to listen for ArtNet packets");
ABSL_FLAG(int, port, 6454, "Port to listen for ArtNet packets");
ABSL_FLAG(int, universes_per_layer, 6, "Number of universes per layer");
ABSL_FLAG(float, alpha, 0.5, "Alpha value for voxel colors");
ABSL_FLAG(int, layer_span, 1, "Layer span (1 for 1:1 mapping)");

// Entry point
int main(int argc, char *argv[]) {
  // Parse command-line arguments using Abseil
  absl::ParseCommandLine(argc, argv);

  try {
    // Extract parsed arguments
    std::string geometry = absl::GetFlag(FLAGS_geometry);
    std::string ip = absl::GetFlag(FLAGS_ip);
    int port = absl::GetFlag(FLAGS_port);
    int universes_per_layer = absl::GetFlag(FLAGS_universes_per_layer);
    int layer_span = absl::GetFlag(FLAGS_layer_span);

    float alpha = absl::GetFlag(FLAGS_alpha);

    // Parse geometry dimensions
    int width, height, length;
    if (sscanf(geometry.c_str(), "%dx%dx%d", &width, &height, &length) != 3) {
      throw std::runtime_error(
          "Invalid geometry format. Use WIDTHxHEIGHTxLENGTH (e.g., 16x16x16).");
    }

    std::cout << "Starting Volumetric Display with the following parameters:\n";
    std::cout << "Geometry: " << width << "x" << height << "x" << length
              << "\n";
    std::cout << "IP: " << ip << "\n";
    std::cout << "Port: " << port << "\n";
    std::cout << "Universes per layer: " << universes_per_layer << "\n";

    // Create and run the volumetric display
    VolumetricDisplay display(width, height, length, ip, port,
                              universes_per_layer, layer_span, alpha);
    display.run();

  } catch (const std::exception &ex) {
    std::cerr << "Error: " << ex.what() << std::endl;
    return EXIT_FAILURE;
  }

  return EXIT_SUCCESS;
}
