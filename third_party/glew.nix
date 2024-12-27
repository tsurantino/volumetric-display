with import <nixpkgs> { };
let
  pkg = glew.overrideAttrs (oldAttrs: {
    postInstall = (oldAttrs.postInstall or "") + ''
      find $out
      # Move all .dylib and .so files to .dev/lib/
      cp lib/*.dylib "''${!outputDev}/lib/"
    '';
  });
in
symlinkJoin {
  name = "glew-joined";
  paths = [
    pkg
  ] ++ lib.optionals (builtins.hasAttr "dev" pkg) [
    pkg.dev
  ] ++ lib.optionals (builtins.hasAttr "bin" pkg) [
    pkg.bin
  ];
}
