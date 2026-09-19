#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdlib.h>
#include <string.h>

static const char *TAG = "mic_test";

#define SAMPLE_RATE  16000
#define SCK_PIN      GPIO_NUM_5
#define WS_PIN       GPIO_NUM_6
#define SD_PIN       GPIO_NUM_4

#define BUF_SAMPLES  256

static i2s_chan_handle_t s_rx_chan;

static void i2s_mic_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &s_rx_chan));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = SCK_PIN,
            .ws   = WS_PIN,
            .dout = I2S_GPIO_UNUSED,
            .din  = SD_PIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_rx_chan, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_rx_chan));
}

void app_main(void)
{
    ESP_LOGI(TAG, "INMP441 mic test starting, SCK=%d WS=%d SD=%d", SCK_PIN, WS_PIN, SD_PIN);
    i2s_mic_init();

    int32_t samples[BUF_SAMPLES];

    while (1) {
        size_t bytes_read = 0;
        esp_err_t err = i2s_channel_read(s_rx_chan, samples, sizeof(samples), &bytes_read, portMAX_DELAY);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "read failed: %s", esp_err_to_name(err));
            continue;
        }

        int n = bytes_read / sizeof(int32_t);
        int64_t sum = 0;
        int32_t peak = 0;
        for (int i = 0; i < n; i++) {
            int32_t s = samples[i] >> 14;
            int32_t a = abs(s);
            sum += a;
            if (a > peak) peak = a;
        }
        int avg = n ? (int)(sum / n) : 0;

        char bar[51];
        int bars = peak / 500;
        if (bars > 50) bars = 50;
        memset(bar, '#', bars);
        bar[bars] = '\0';

        ESP_LOGI(TAG, "avg:%6d peak:%6d %s", avg, (int)peak, bar);
    }
}
