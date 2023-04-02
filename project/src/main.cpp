#include <cstdio>
#include <iostream>
#include <fstream>
#include <string>

#include "script_executor.h"

#include "../3rdparty/include/httplib.h"

void writeToFile(std::string path, std::string content) {
    std::ofstream file;
    file.open(path);
    file << content;
    file.close();
}


void getModel(std::string path, std::string model) {
    httplib::Client cli("http://185.187.169.44:10073");
    cli.set_basic_auth("team1", "PQWK7WdSdmrej6TC3xaf");

    auto res = cli.Get(("/team1?getModel=" + model).c_str());

    writeToFile(path + model, res->body);

    std::puts("Model loaded!");

    writeToFile(path + "latestModel.txt", model);
}

int main()
{
    

    // HTTPS
    httplib::Client cli("http://185.187.169.44:10073");
    cli.set_basic_auth("team1", "PQWK7WdSdmrej6TC3xaf");

    std::puts("Loading model from server...");
    auto res = cli.Get("/team1?listModels");
    // std::cout << res->status << std::endl;
    // std::cout << res->body << std::endl;
    
    // parse list to array
    std::string list = res->body;

    std::vector<std::string> models;

    bool closedHiphens = true;
    int lastHiphens = 0;
    for (int i = 0; i < list.length(); i++) {
        if (list[i] == '"') {
            closedHiphens = !closedHiphens;
            if (closedHiphens) {
                models.push_back(list.substr(lastHiphens, i - lastHiphens));
            }
            else {
                lastHiphens = i + 1;
            }
        }
    }

    int latestModel = 0, latestModelIndex = 0;
    for (int i = 0; i < models.size(); i++) {
        // find position of last .
        int lastDot = 0;
        for (int j = models[i].length(); j >= 0; j--) {
            if (models[i][j] == '.') {
                lastDot = j;
                break;
            }
        }

        std::string model = models[i].substr(0, lastDot);

        // get number of model
        int modelNumber = 0;
        for (int j = 0; j < model.length(); j++) {
            if (model[j] >= '0' && model[j] <= '9') {
                modelNumber = modelNumber * 10 + (model[j] - '0');
            }
        }

        if (modelNumber > latestModel) {
            latestModel = modelNumber;
            latestModelIndex = i;
        }
    }

    std::string latestModelName = models[latestModelIndex];

    res = cli.Get(("/team1?modelName=" + latestModelName).c_str());
    std::puts("Model loaded!");

    std::string path = "/home/rpy/";

    std::cout << "Model name: " << latestModelName << std::endl;
    writeToFile(path + latestModelName, res->body);

    

    writeToFile(path + "latestModel.txt", latestModelName);

    auto py_std_out = std::string{};
    const auto py_ret = execute_python_script("/usr/share/StudentContest/main.py", &py_std_out);
    std::printf("%s", py_std_out.c_str());

    std::cout << "Python script returned: " << py_ret << std::endl;
    std::cout << "Sending result to server..." << std::endl;

    // split by . 
    std::string latestModelNameWithoutExtension = latestModelName.substr(0, latestModelName.find_last_of("."));

    // read results from file
    std::ifstream file;
    file.open("/usr/share/StudentContest/" + latestModelNameWithoutExtension + "_results.json");
    std::string results;
    // read whole file into results string
    while (file.good()) {
        std::string line;
        std::getline(file, line);
        results += line;
    }
    file.close();

    std::cout <<  results << std::endl;

    res = cli.Post("/team1?uploadResults", results.c_str(), "application/json");

    if (res->status == 200) {
        std::cout << "Results uploaded successfully!" << std::endl;
    }
    else {
        std::cout << "Results upload failed!" << std::endl;
    }

    return py_ret;
}
