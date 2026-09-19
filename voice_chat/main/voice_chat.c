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
#include "lwip/sockets.h"
#include "lwip/netdb.h"

static const char *TAG = "voice_chat";

#define SPK_SAMPLE_RATE 44100
#define SPK_BCLK_PIN    GPIO_NUM_15
#define SPK_WS_PIN      GPIO_NUM_16
#define SPK_DOUT_PIN    GPIO_NUM_17

#define MIC_SAMPLE_RATE 16000
#define MIC_SCK_PIN     GPIO_NUM_5
#define MIC_WS_PIN      GPIO_NUM_6
#define MIC_SD_PIN      GPIO_NUM_4
#define MIC_BUF_SAMPLES 256

#define WIFI_CONNECTED_BIT BIT0
#define AUDIO_RING_BYTES    (64 * 1024)

static EventGroupHandle_t s_wifi_event_group;
static StreamBufferHandle_t s_audio_ring;
static i2s_chan_handle_t s_tx_chan;
static i2s_chan_handle_t s_rx_chan;

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
            .ssid = CONFIG_VOICE_WIFI_SSID,
            .password = CONFIG_VOICE_WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "connecting to %s", CONFIG_VOICE_WIFI_SSID);
    xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

static void i2s_speaker_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &s_tx_chan, NULL));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SPK_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = SPK_BCLK_PIN,
            .ws   = SPK_WS_PIN,
            .dout = SPK_DOUT_PIN,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_tx_chan, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_tx_chan));
}

static void i2s_mic_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &s_rx_chan));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(MIC_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = MIC_SCK_PIN,
            .ws   = MIC_WS_PIN,
            .dout = I2S_GPIO_UNUSED,
            .din  = MIC_SD_PIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_rx_chan, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_rx_chan));
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

static void speak_stream_task(void *arg)
{
    while (1) {
        esp_http_client_config_t config = {
            .url = CONFIG_VOICE_SPEAK_URL,
            .event_handler = http_event_handler,
            .timeout_ms = 60000, // long enough to cover ASR+LLM+TTS think time before the first chunk
        };
        esp_http_client_handle_t client = esp_http_client_init(&config);

        esp_err_t err = esp_http_client_perform(client);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "turn done, status=%d", esp_http_client_get_status_code(client));
        } else {
            ESP_LOGE(TAG, "speak_stream failed: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
        esp_http_client_cleanup(client);
    }
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

static int mic_connect(void)
{
    struct sockaddr_in dest = {
        .sin_family = AF_INET,
        .sin_port = htons(CONFIG_VOICE_MIC_PORT),
    };
    dest.sin_addr.s_addr = inet_addr(CONFIG_VOICE_HOST_IP);

    int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock < 0) {
        ESP_LOGE(TAG, "mic socket() failed: errno %d", errno);
        return -1;
    }
    if (connect(sock, (struct sockaddr *)&dest, sizeof(dest)) != 0) {
        ESP_LOGE(TAG, "mic connect() failed: errno %d", errno);
        close(sock);
        return -1;
    }
    ESP_LOGI(TAG, "mic upload connected to %s:%d", CONFIG_VOICE_HOST_IP, CONFIG_VOICE_MIC_PORT);
    return sock;
}

static void mic_upload_task(void *arg)
{
    int32_t raw[MIC_BUF_SAMPLES];
    int16_t pcm16[MIC_BUF_SAMPLES];

    while (1) {
        int sock = mic_connect();
        if (sock < 0) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        bool link_ok = true;
        while (link_ok) {
            size_t bytes_read = 0;
            esp_err_t err = i2s_channel_read(s_rx_chan, raw, sizeof(raw), &bytes_read, portMAX_DELAY);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "mic read failed: %s", esp_err_to_name(err));
                continue;
            }

            int n = bytes_read / sizeof(int32_t);
            for (int i = 0; i < n; i++) {
                pcm16[i] = (int16_t)(raw[i] >> 14);
            }

            const uint8_t *data = (const uint8_t *)pcm16;
            int remaining = n * sizeof(int16_t);
            while (remaining > 0) {
                int sent = send(sock, data, remaining, 0);
                if (sent < 0) {
                    ESP_LOGE(TAG, "mic send() failed: errno %d", errno);
                    link_ok = false;
                    break;
                }
                data += sent;
                remaining -= sent;
            }
        }

        close(sock);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());

    s_audio_ring = xStreamBufferCreate(AUDIO_RING_BYTES, 1);

    wifi_init_sta();
    i2s_speaker_init();
    i2s_mic_init();

    xTaskCreate(i2s_drain_task, "i2s_drain", 4096, NULL, 6, NULL);
    xTaskCreate(speak_stream_task, "speak_stream", 8192, NULL, 5, NULL);
    xTaskCreate(mic_upload_task, "mic_upload", 4096, NULL, 5, NULL);
}
