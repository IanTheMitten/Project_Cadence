#include <string.h>
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "nvs_flash.h"

static const char *TAG = "cadence_speaker";

#define SAMPLE_RATE 44100
#define BCLK_PIN    GPIO_NUM_15
#define WS_PIN      GPIO_NUM_16
#define DOUT_PIN    GPIO_NUM_17

#define WIFI_CONNECTED_BIT BIT0
#define AUDIO_RING_BYTES    (64 * 1024)

static EventGroupHandle_t s_wifi_event_group;
static StreamBufferHandle_t s_audio_ring;
static i2s_chan_handle_t s_tx_chan;

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi disconnected, retrying");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *) event_data;
        ESP_LOGI(TAG, "got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = CONFIG_MUSE_WIFI_SSID,
            .password = CONFIG_MUSE_WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "connecting to %s", CONFIG_MUSE_WIFI_SSID);
    xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

static void i2s_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &s_tx_chan, NULL));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = BCLK_PIN,
            .ws   = WS_PIN,
            .dout = DOUT_PIN,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_tx_chan, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_tx_chan));
}

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    if (evt->event_id == HTTP_EVENT_ON_DATA) {
        const uint8_t *data = evt->data;
        int remaining = evt->data_len;
        while (remaining > 0) {
            size_t sent = xStreamBufferSend(s_audio_ring, data, remaining, portMAX_DELAY);
            data += sent;
            remaining -= sent;
        }
    }
    return ESP_OK;
}

static void http_stream_task(void *arg)
{
    esp_http_client_config_t config = {
        .url = CONFIG_MUSE_PROXY_URL,
        .event_handler = http_event_handler,
        .timeout_ms = 20000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);

    ESP_LOGI(TAG, "requesting %s", CONFIG_MUSE_PROXY_URL);
    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "stream done, status=%d", esp_http_client_get_status_code(client));
    } else {
        ESP_LOGE(TAG, "stream failed: %s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    vTaskDelete(NULL);
}

static void i2s_drain_task(void *arg)
{
    int16_t buf[256];
    while (1) {
        size_t got = xStreamBufferReceive(s_audio_ring, buf, sizeof(buf), portMAX_DELAY);
        if (got == 0) {
            continue;
        }
        size_t written;
        i2s_channel_write(s_tx_chan, buf, got, &written, portMAX_DELAY);
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());

    s_audio_ring = xStreamBufferCreate(AUDIO_RING_BYTES, 1);

    wifi_init_sta();
    i2s_init();

    xTaskCreate(i2s_drain_task, "i2s_drain", 4096, NULL, 6, NULL);
    xTaskCreate(http_stream_task, "http_stream", 8192, NULL, 5, NULL);
}
