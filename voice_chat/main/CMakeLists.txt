idf_component_register(SRCS "voice_chat.c"
                    INCLUDE_DIRS "."
                    PRIV_REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_http_client esp_driver_i2s esp_driver_gpio lwip)
