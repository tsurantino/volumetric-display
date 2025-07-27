from artnet import Scene, RGB, HSV
import math

class RainbowScene(Scene):
    def __init__(self, config=None):
        pass

    def render(self, raster, time):
        """
        Fills the entire raster with a moving 3D rainbow gradient.
        """
        # Iterate over every logical voxel in the display
        for z in range(raster.length):
            for y in range(raster.height):
                for x in range(raster.width):
                    
                    # Calculate a hue value that changes based on the voxel's
                    # position and the elapsed time. This creates the animation.
                    hue = (x + y + z) * 3 + time * 50
                    
                    # Convert the calculated hue into an RGB color
                    color = RGB.from_hsv(HSV(
                        int(hue) % 256,  # Hue cycles from 0-255
                        255,             # Full saturation
                        255              # Full brightness
                    ))

                    # Use raster.set_pix() to correctly place the voxel
                    # in the display's transformed coordinate space.
                    raster.set_pix(x, y, z, color)