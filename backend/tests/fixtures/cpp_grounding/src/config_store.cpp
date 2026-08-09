#include <filesystem>
#include <fstream>

std::filesystem::path settingsPath()
{
    return std::filesystem::current_path() / "config" / "settings.json";
}

void persistSettings(const std::string& contents)
{
    std::filesystem::create_directories(settingsPath().parent_path());
    std::ofstream output(settingsPath());
    output << contents;
}

int main()
{
    persistSettings("{}");
    return 0;
}
