from artnet import Scene, RGB
import math

class RainbowScene(Scene):
    def render(self, raster, time):
        for y in range(raster.height):
            for x in range(raster.width):
                for z in range(raster.length):
                    idx = y * raster.width + x + z * raster.width * raster.height
                    
                    # Create a moving rainbow pattern
                    hue = (x + y + z) / 10.0 + time * 0.5
                    
                    # Convert hue to RGB (simplified conversion)
                    red = int(255 * (math.sin(hue) * 0.5 + 0.5))
                    green = int(255 * (math.sin(hue + 2.094) * 0.5 + 0.5))
                    blue = int(255 * (math.sin(hue + 4.189) * 0.5 + 0.5))
                    
                    raster.data[idx] = RGB(red, green, blue)
