{
  description = "Source-pinned Google Android Emulator build environment";
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
  };
  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = import nixpkgs { inherit system; }; in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [ git git-repo python3 cmake ninja ccache curl unzip zip pkg-config ];
        };
      } // pkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
        packages.default = pkgs.callPackage ./nix/fhs.nix { };
      });
}
