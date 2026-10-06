cmake_minimum_required(VERSION 3.16)

# Committed defaults first, then the gitignored local override (WiFi SSID/password).
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults")
if(EXISTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults.local")
    list(APPEND SDKCONFIG_DEFAULTS "sdkconfig.defaults.local")
else()
    message(WARNING "voice_chat/sdkconfig.defaults.local not found: WiFi SSID/password stay empty. See CLAUDE.md.")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(voice_chat)
