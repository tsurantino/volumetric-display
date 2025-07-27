#include "VolumetricDisplay.h"
#include <glm/glm.hpp>
#include <iostream>
#include <string>
#include <vector>

// A helper function to print usage instructions
void printUsage(const char* prog_name) {
    std::cerr << "Usage: " << prog_name << " -c <path_to_config.json> [options]\n\n"
              << "Required:\n"
              << "  -c, --config <path>    Path to the display configuration JSON file.\n\n"
              << "Options:\n"
              << "  -a, --alpha <value>    Alpha value for voxel transparency (0.0 to 1.0). Default: 0.7\n"
              << "  -r, --rotation <X,Y,Z> Initial rotation rate in degrees/sec. Default: 0,10,0\n"
              << "  --color-correction     Enable WS2812B color correction. Default: enabled\n"
              << "  --no-color-correction  Disable WS2812B color correction.\n"
              << "  -h, --help             Print this usage message.\n";
}

int main(int argc, char* argv[]) {
    // Default values for our settings
    std::string config_path = "";
    float alpha = 0.7f;
    glm::vec3 rotation_rate = glm::vec3(0.0f, glm::radians(10.0f), 0.0f); // Default: 10 degrees/sec on Y-axis
    bool color_correction_enabled = true;

    // Manual command-line argument parsing
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if ((arg == "-h") || (arg == "--help")) {
            printUsage(argv[0]);
            return 0;
        } else if ((arg == "-c") || (arg == "--config")) {
            if (i + 1 < argc) { // Make sure we have a value after the flag
                config_path = argv[++i];
            } else {
                std::cerr << "Error: --config option requires one argument." << std::endl;
                return 1;
            }
        } else if ((arg == "-a") || (arg == "--alpha")) {
            if (i + 1 < argc) {
                try {
                    alpha = std::stof(argv[++i]);
                } catch (const std::invalid_argument& ia) {
                    std::cerr << "Error: Invalid alpha value." << std::endl;
                    return 1;
                }
            } else {
                std::cerr << "Error: --alpha option requires one argument." << std::endl;
                return 1;
            }
        } else if ((arg == "-r") || (arg == "--rotation")) {
             if (i + 1 < argc) {
                std::string rates_str = argv[++i];
                size_t first_comma = rates_str.find(',');
                size_t second_comma = rates_str.rfind(',');
                if (first_comma != std::string::npos && second_comma != std::string::npos && first_comma != second_comma) {
                    try {
                        float x = std::stof(rates_str.substr(0, first_comma));
                        float y = std::stof(rates_str.substr(first_comma + 1, second_comma - first_comma - 1));
                        float z = std::stof(rates_str.substr(second_comma + 1));
                        rotation_rate = glm::vec3(glm::radians(x), glm::radians(y), glm::radians(z));
                    } catch (const std::exception& e) {
                        std::cerr << "Error: Invalid format for rotation rate. Use X,Y,Z" << std::endl;
                        return 1;
                    }
                }
            } else {
                std::cerr << "Error: --rotation option requires one argument." << std::endl;
                return 1;
            }
        } else if (arg == "--color-correction") {
            color_correction_enabled = true;
        } else if (arg == "--no-color-correction") {
            color_correction_enabled = false;
        }
    }

    // Check if the required config path was provided
    if (config_path.empty()) {
        std::cerr << "Error: Configuration file path is required." << std::endl;
        printUsage(argv[0]);
        return 1;
    }

    // Run the application
    try {
        VolumetricDisplay display(config_path, alpha, rotation_rate, color_correction_enabled);
        display.run();
    } catch (const std::exception& e) {
        std::cerr << "An error occurred: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}