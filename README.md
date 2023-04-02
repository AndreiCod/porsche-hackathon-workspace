# Welcome!

This part of your assignment consists of a C++ project that must retrieve a model from an HTTP endpoint, once obtained, run inference using this model, by invoking a python script, and uploading the results to the same endpoint.

## Some information to help you on your way

### Project structure
```
┌─project
│  ├───.vscode        <- Tasks and configurations used by VS Code for building and running the project
│  ├───3rdparty       <- Http client and json parser
│  ├───bin            <- Scripts used for deployment and debugging
│  ├───include        <- Your header files (.h)
│  ├───src            <- Your source files (.cpp)
│  │    └───python    <- Python scripts used by the project
│  ├───CMakeLists.txt <- The main project file
│  ├───ssh_id         <- Private key used to publish files to the target device (Raspberry Pi)
│  └───ssh_id.pub     <- Public key used to publish files to the target device (Raspberry Pi)
│
├─toolchain           <- Compiler, linker, build system, etc.
├─open_project.bat    <- Sets up the environment and runs VS Code
└─README.md           <- This file
```

### Coding and deployment

You only need to make changes in the `include` and `src` directories when you add new source files to your project. Make sure to add your new `.cpp` files to `CMakeLists.txt` in the [`target_sources`](https://cmake.org/cmake/help/latest/command/target_sources.html) CMake function.

In order to execute a Python script from your C++ code include `script_executor.h` and run the `execute_python_script` function.

Also take note that only `.py` files in the `src/python` directory will be deployed to the target device (Raspberry Pi), this does **NOT** include any subdirectories. All python files are deployed to `/usr/share/StudentContest` on the target device.

In order to connect to the Raspberry Pi via `SSH` open a terminal in VS Code and run: `ssh.exe -i ssh_id -p $env:RPI_SSH_PORT root@$env:RPI_IP_ADDR`.

If you require any dependencies for your Python scripts connect to the target device and install them via `pip` or `apt`.

### Documentation

You can find reference documentation for the C++ standard library here at [`https://en.cppreference.com/w/`](https://en.cppreference.com/w/); make sure to keep in mind that this project uses C++17, so avoid anything marked C++20 or above.

The documentation for `cpp-httplib`, the HTTP client library can be found at [`https://github.com/yhirose/cpp-httplib`](https://github.com/yhirose/cpp-httplib).

The documentation for `nlohmann::json`, the JSON parsing library can be found at [`https://github.com/nlohmann/json#examples`](https://github.com/nlohmann/json#examples).

If you are interested feel free to check out CMake documentation: [`https://cmake.org/cmake/help/latest/`](https://cmake.org/cmake/help/latest/).
