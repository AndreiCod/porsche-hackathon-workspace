#pragma once

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <thread>

///  Executes a Python script and captures its standard output and error streams.
///  This function creates a new process by forking the current one, and executes the Python interpreter
///  with the specified script as its argument. The standard output and error streams of the child process
///  are redirected to pipes, which are read by the parent process and optionally stored in string buffers.
///
///  @param script_path The path to the Python script to execute.
///  @param std_out Pointer to a string buffer to store the standard output of the Python script. If this parameter is nullptr, the standard output is not captured.
///  @param std_err Pointer to a string buffer to store the standard error of the Python script. If this parameter is nullptr, the standard error is not captured.
///  @return The exit code of the Python script, or MAX_INT if an error occurred.
///  @throws None
int execute_python_script(std::string_view script_path, std::string *std_out = nullptr, std::string *std_err = nullptr) noexcept
{
    int pipe_std_out[2];
    if (pipe(pipe_std_out) != 0)
    {
        const auto err = errno;
        std::fprintf(stderr, "Failed to create pipe for standard output: %s (%d)\n", err, std::strerror(err));
    }

    int pipe_std_err[2];
    if (pipe(pipe_std_err) != 0)
    {
        const auto err = errno;
        std::fprintf(stderr, "Failed to create pipe for standard error: %s (%d)\n", err, std::strerror(err));
    }

    const auto ret = fork();
    if (ret == -1)
    {
        const auto err = errno;
        std::fprintf(stderr, "Failed to spawn Python process: %s (%d)\n", err, std::strerror(err));

        return std::numeric_limits<int>::max();
    }

    // Child process
    if (ret == 0)
    {
        // Close the reading end of the pipes
        close(pipe_std_out[0]); 
        close(pipe_std_err[0]); 

        // Send stdout to the pipe
        dup2(pipe_std_out[1], 1);

        // Send stderr to the pipe
        dup2(pipe_std_err[1], 2);  

        // The descriptors are no longer needed
        close(pipe_std_out[1]); 
        close(pipe_std_err[1]); 
        
        if (execl("/root/.pyenv/versions/3.7.16/bin/python", "/root/.pyenv/versions/3.7.16/bin/python", script_path.data(), nullptr) < 0)
        {
            const auto err = errno;
            std::fprintf(stderr, "Failed to spawn Python process: %s (%d)\n", err, std::strerror(err));

            std::exit(std::numeric_limits<int>::max());
        }
    }
    // Parent process
    else
    {
        auto std_out_buffer = std::array<char, 1024>{};
        auto std_err_buffer = std::array<char, 1024>{};
        
        // Close the write end of the pipes
        close(pipe_std_out[1]); 
        close(pipe_std_err[1]); 

        auto std_out_reader = std::thread{};
        auto std_err_reader = std::thread{};

        if (std_out != nullptr)
        {
            std_out_reader = std::thread { [&std_out_buffer, &pipe_std_out, std_out] {
                for (;;)
                {
                    const auto bytes_read = read(pipe_std_out[0], std_out_buffer.data(), std_out_buffer.size() - 1);
                    if (bytes_read < 0)
                    {
                        const auto err = errno;
                        std::fprintf(stderr, "Failed to read standard output from the Python process: %s (%d)\n", err, std::strerror(err));
                        break;
                    }

                    if (bytes_read > 0)
                    {
                        std_out_buffer[static_cast<std::size_t>(bytes_read)] = '\0';
                        (*std_out) += std_out_buffer.data();

                        continue;
                    }

                    break;
                }
            }};
        }

        if (std_err != nullptr)
        {
            std_err_reader = std::thread { [&std_err_buffer, &pipe_std_err, std_err] {
                for (;;)
                {
                    const auto bytes_read = read(pipe_std_err[0], std_err_buffer.data(), std_err_buffer.size() - 1);
                    if (bytes_read < 0)
                    {
                        const auto err = errno;
                        std::fprintf(stderr, "Failed to read standard error from the Python process: %s (%d)\n", err, std::strerror(err));
                        break;
                    }
                    if (bytes_read > 0)
                    {
                        std_err_buffer[static_cast<std::size_t>(bytes_read)] = '\0';
                        (*std_err) += std_err_buffer.data();

                        continue;
                    }

                    break;
                }
            }};
        }

        if (std_out_reader.joinable())
        {
            std_out_reader.join();
        }

        if (std_err_reader.joinable())
        {
            std_err_reader.join();
        }

        close(pipe_std_out[0]); 
        close(pipe_std_err[0]); 

        auto stat_loc = int{};
        waitpid(ret, &stat_loc, 0);

        return WEXITSTATUS(stat_loc);
    }

    return std::numeric_limits<int>::max();
}