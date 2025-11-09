{
	description = "Bouncy DVD-like terminal screensaver for Hyprland";

	inputs = {
		nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
		flake-utils.url = "github:numtide/flake-utils";
		home-manager = {
			url = "github:nix-community/home-manager";
			inputs.nixpkgs.follows = "nixpkgs";
		};
	};

	outputs = { self, nixpkgs, flake-utils, home-manager }:
		flake-utils.lib.eachDefaultSystem (system:
			let
				pkgs = nixpkgs.legacyPackages.${system};
				
				hyprdvd = pkgs.python3Packages.buildPythonApplication {
					pname = "hyprdvd";
					version = "0.5.0";
					
					src = ./.;
					
					pyproject = true;
					
					nativeBuildInputs = with pkgs.python3Packages; [
						setuptools
					];
					
					propagatedBuildInputs = with pkgs.python3Packages; [
						argcomplete
					];
					
					# Skip tests since there are none in the repository
					doCheck = false;
					
					meta = with pkgs.lib; {
						description = "Bouncy DVD-like terminal screensaver for Hyprland";
						homepage = "https://github.com/nevimmu/hyprdvd";
						license = licenses.mit;
						maintainers = [ ];
						platforms = platforms.linux; # Hyprland is Linux-only
						mainProgram = "hyprdvd";
					};
				};
			in
			{
				packages = {
					default = hyprdvd;
					hyprdvd = hyprdvd;
				};

				apps = {
					default = flake-utils.lib.mkApp {
						drv = hyprdvd;
						name = "hyprdvd";
					};
					hyprdvd = flake-utils.lib.mkApp {
						drv = hyprdvd;
						name = "hyprdvd";
					};
				};

				devShells.default = pkgs.mkShell {
					buildInputs = with pkgs; [
						python3
						python3Packages.setuptools
						python3Packages.argcomplete
						commitizen
						pipx
					];
					
					shellHook = ''
						export PATH="$HOME/.local/bin:$PATH"
						echo "HyprDVD development environment"
						echo "Run 'pipx install -e .' to install in development mode"
					'';
				};
			}
		) // {
			# Home Manager module
			homeManagerModules.default = { config, lib, pkgs, ... }:
				with lib;
				let
					cfg = config.services.hyprdvd;
				in
				{
					options.services.hyprdvd = {
						enable = mkEnableOption "hyprdvd bouncing DVD screensaver service";
						
						package = mkOption {
							type = types.package;
							default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
							description = "The hyprdvd package to use";
						};
						
						autoStart = mkOption {
							type = types.bool;
							default = false;
							description = "Whether to automatically start hyprdvd with Hyprland";
						};
					};
					
					config = mkIf cfg.enable {
						home.packages = [ cfg.package ];
						
						# Add to Hyprland config if autoStart is enabled
						wayland.windowManager.hyprland = mkIf cfg.autoStart {
							settings = {
								exec-once = [ "${cfg.package}/bin/hyprdvd" ];
							};
						};
					};
				};
			
			# Home Manager module alias for convenience
			homeManagerModules.hyprdvd = self.homeManagerModules.default;
		};
}
