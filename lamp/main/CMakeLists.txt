idf_component_register(SRCS "lamp.c"
                    INCLUDE_DIRS "."
                    PRIV_REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_websocket_client esp_driver_ledc esp_driver_gpio
                                  esp_https_ota esp_http_client app_update esp_app_format json)
