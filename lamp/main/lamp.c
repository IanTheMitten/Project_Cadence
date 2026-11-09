// Cadence ceiling lamp: CCT strip (cool + warm white) on two low-side N-MOSFETs.
// Joins Cadence /peer as a device and exposes raw channel duty; all tuning lives in the harness.
#include <string.h>
#include "cJSON.h"
#include "driver/ledc.h"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_https_ota.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "lamp";

#define COOL_PIN        GPIO_NUM_4
#define WARM_PIN        GPIO_NUM_2
#define COOL_CH         LEDC_CHANNEL_0
#define WARM_CH         LEDC_CHANNEL_1
#define LEDC_MODE       LEDC_LOW_SPEED_MODE
// IRLZ44N on 3.3 V through 220 ohm switches in ~5-10 us; at 2 kHz that is a few % of the period, not half.
#define PWM_HZ          2000
#define PWM_RES         LEDC_TIMER_14_BIT // 80 MHz / 2 kHz = 40000 ticks; 14 bits fits, finer low-end dimming
#define DUTY_MAX        (1u << 14)
#define DEFAULT_FADE_MS 400
#define MAX_FADE_MS     600000
#define BOOT_FADE_MS    300
#define FIRST_BOOT_PCT  50.0f            // no saved state yet: wall switch must still give light

#define WIFI_CONNECTED_BIT BIT0

typedef struct { float cool, warm; } lamp_state_t;  // PWM duty percent, 0..100

static lamp_state_t s_state;
static EventGroupHandle_t s_wifi_event_group;
static esp_websocket_client_handle_t s_ws;

// ---- light ----

static void led_init(void)
{
    ledc_timer_config_t t = {
        .speed_mode = LEDC_MODE, .duty_resolution = PWM_RES, .timer_num = LEDC_TIMER_0,
        .freq_hz = PWM_HZ, .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&t));
    ledc_channel_config_t c = {.speed_mode = LEDC_MODE, .timer_sel = LEDC_TIMER_0, .duty = 0};
    c.channel = COOL_CH; c.gpio_num = COOL_PIN; ESP_ERROR_CHECK(ledc_channel_config(&c));
    c.channel = WARM_CH; c.gpio_num = WARM_PIN; ESP_ERROR_CHECK(ledc_channel_config(&c));
    ESP_ERROR_CHECK(ledc_fade_func_install(0));
}

static void set_channel(ledc_channel_t ch, float pct, uint32_t fade_ms)
{
    uint32_t duty = (uint32_t)(pct / 100.0f * DUTY_MAX + 0.5f);
    ledc_fade_stop(LEDC_MODE, ch);  // a new command interrupts a running fade instead of queueing behind it
    if (fade_ms == 0) {
        ledc_set_duty_and_update(LEDC_MODE, ch, duty, 0);
    } else {
        ledc_set_fade_time_and_start(LEDC_MODE, ch, duty, fade_ms, LEDC_FADE_NO_WAIT);
    }
}

static void apply(lamp_state_t st, uint32_t fade_ms)
{
    set_channel(COOL_CH, st.cool, fade_ms);
    set_channel(WARM_CH, st.warm, fade_ms);
    s_state = st;
}

static void state_save(void)
{
    nvs_handle_t h;
    if (s_state.cool == 0 && s_state.warm == 0) return;  // keep last lit level, so the wall switch always gives light
    if (nvs_open("lamp", NVS_READWRITE, &h) != ESP_OK) return;
    nvs_set_blob(h, "state", &s_state, sizeof(s_state));
    nvs_commit(h);
    nvs_close(h);
}

static lamp_state_t state_load(void)
{
    lamp_state_t st = {FIRST_BOOT_PCT, FIRST_BOOT_PCT};
    nvs_handle_t h;
    if (nvs_open("lamp", NVS_READONLY, &h) == ESP_OK) {
        size_t len = sizeof(st);
        lamp_state_t saved;
        if (nvs_get_blob(h, "state", &saved, &len) == ESP_OK && len == sizeof(saved)) st = saved;
        nvs_close(h);
    }
    return st;
}

// ---- wifi (same as voice_chat) ----

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi disconnected (reason %d), retrying", ((wifi_event_sta_disconnected_t *)data)->reason);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ESP_LOGI(TAG, "got IP: " IPSTR, IP2STR(&((ip_event_got_ip_t *)data)->ip_info.ip));
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
    wifi_config_t wc = {.sta = {.ssid = CONFIG_LAMP_WIFI_SSID, .password = CONFIG_LAMP_WIFI_PASSWORD}};
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));  // modem sleep delays commands by up to a DTIM period; lamp is mains powered
    ESP_LOGI(TAG, "connecting to %s", CONFIG_LAMP_WIFI_SSID);
    xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

// ---- OTA: pulled once per boot, so power-cycling the wall switch updates ----

static bool same_image(const esp_app_desc_t *a, const esp_partition_t *p)
{
    esp_app_desc_t d;
    return p && esp_ota_get_partition_description(p, &d) == ESP_OK &&
           memcmp(a->app_elf_sha256, d.app_elf_sha256, sizeof(d.app_elf_sha256)) == 0;
}

static void ota_check(void)
{
    if (CONFIG_LAMP_OTA_URL[0] == '\0') return;
    esp_http_client_config_t http = {.url = CONFIG_LAMP_OTA_URL, .timeout_ms = 5000, .keep_alive_enable = true};
    esp_https_ota_config_t cfg = {.http_config = &http};
    esp_https_ota_handle_t h = NULL;
    if (esp_https_ota_begin(&cfg, &h) != ESP_OK) {
        ESP_LOGI(TAG, "no OTA image at %s", CONFIG_LAMP_OTA_URL);
        return;
    }
    esp_app_desc_t img;
    if (esp_https_ota_get_img_desc(h, &img) != ESP_OK ||
        same_image(&img, esp_ota_get_running_partition()) ||
        same_image(&img, esp_ota_get_last_invalid_partition())) {  // never re-flash an image that already rolled back
        esp_https_ota_abort(h);
        return;
    }
    ESP_LOGI(TAG, "OTA: flashing %s", img.version);
    esp_err_t err;
    while ((err = esp_https_ota_perform(h)) == ESP_ERR_HTTPS_OTA_IN_PROGRESS) {}
    if (err == ESP_OK && esp_https_ota_is_complete_data_received(h) && esp_https_ota_finish(h) == ESP_OK) {
        ESP_LOGI(TAG, "OTA done, restarting");
        esp_restart();
    }
    ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(err));
    esp_https_ota_abort(h);
}

// ---- Cadence /peer ----

static void send_json(cJSON *msg)
{
    char *s = cJSON_PrintUnformatted(msg);
    if (s) {
        esp_websocket_client_send_text(s_ws, s, strlen(s), portMAX_DELAY);
        cJSON_free(s);
    }
    cJSON_Delete(msg);
}

static cJSON *state_json(void)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "cool", s_state.cool);
    cJSON_AddNumberToObject(o, "warm", s_state.warm);
    return o;
}

static cJSON *pct_param(const char *desc)
{
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "type", "number");
    cJSON_AddNumberToObject(p, "minimum", 0);
    cJSON_AddNumberToObject(p, "maximum", 100);
    cJSON_AddStringToObject(p, "description", desc);
    return p;
}

static void send_hello(void)
{
    cJSON *props = cJSON_CreateObject();
    cJSON_AddItemToObject(props, "cool", pct_param("Cool-white channel PWM duty, percent. Omit to keep current."));
    cJSON_AddItemToObject(props, "warm", pct_param("Warm-white channel PWM duty, percent. Omit to keep current."));
    cJSON *fade = cJSON_AddObjectToObject(props, "fade_ms");
    cJSON_AddStringToObject(fade, "type", "integer");
    cJSON_AddNumberToObject(fade, "minimum", 0);
    cJSON_AddNumberToObject(fade, "maximum", MAX_FADE_MS);
    cJSON_AddStringToObject(fade, "description", "Transition time in ms; default 400, 0 is instant.");
    cJSON *params = cJSON_CreateObject();
    cJSON_AddStringToObject(params, "type", "object");
    cJSON_AddItemToObject(params, "properties", props);

    cJSON *ab = cJSON_CreateObject();
    cJSON_AddStringToObject(ab, "name", "light.set");
    cJSON_AddStringToObject(ab, "description",
        "Set the ceiling lamp's two white LED channels directly. Both 0 is off. "
        "Returns the new cool/warm levels.");
    cJSON_AddItemToObject(ab, "parameters", params);
    cJSON_AddStringToObject(ab, "target", "lamp");

    cJSON *m = cJSON_CreateObject();
    cJSON_AddStringToObject(m, "type", "hello");
    cJSON_AddNumberToObject(m, "version", 1);
    cJSON_AddStringToObject(m, "peer_id", CONFIG_LAMP_PEER_ID);
    cJSON_AddStringToObject(m, "role", "device");
    cJSON_AddStringToObject(m, "kind", "lamp");
    cJSON_AddStringToObject(m, "room", CONFIG_LAMP_ROOM);
    cJSON_AddArrayToObject(m, "caps");
    cJSON_AddItemToArray(cJSON_AddArrayToObject(m, "abilities"), ab);
    send_json(m);
}

static void send_state(void)
{
    cJSON *m = cJSON_CreateObject();
    cJSON_AddStringToObject(m, "type", "state");
    cJSON_AddItemToObject(cJSON_AddObjectToObject(m, "state"), "light", state_json());
    send_json(m);
}

// Reads one optional 0..100 arg. Returns an error string or NULL.
static const char *read_pct(const cJSON *args, const char *key, float *out)
{
    const cJSON *v = cJSON_GetObjectItem(args, key);
    if (v == NULL || cJSON_IsNull(v)) return NULL;
    if (!cJSON_IsNumber(v) || v->valuedouble < 0 || v->valuedouble > 100) return "must be a number 0-100";
    *out = (float)v->valuedouble;
    return NULL;
}

static void handle_call(const cJSON *msg)
{
    const cJSON *cap = cJSON_GetObjectItem(msg, "capability");
    const cJSON *args = cJSON_GetObjectItem(msg, "args");
    char err[64] = "";
    lamp_state_t st = s_state;
    uint32_t fade_ms = DEFAULT_FADE_MS;

    if (!cJSON_IsString(cap) || strcmp(cap->valuestring, "light.set") != 0) {
        snprintf(err, sizeof(err), "unknown capability");
    } else {
        const char *e;
        const cJSON *f = cJSON_GetObjectItem(args, "fade_ms");
        if ((e = read_pct(args, "cool", &st.cool))) {
            snprintf(err, sizeof(err), "cool %s", e);
        } else if ((e = read_pct(args, "warm", &st.warm))) {
            snprintf(err, sizeof(err), "warm %s", e);
        } else if (f && !cJSON_IsNull(f)) {
            if (!cJSON_IsNumber(f) || f->valuedouble < 0 || f->valuedouble > MAX_FADE_MS) {
                snprintf(err, sizeof(err), "fade_ms must be 0-%d", MAX_FADE_MS);
            } else {
                fade_ms = (uint32_t)f->valuedouble;
            }
        }
    }

    if (!err[0]) {
        apply(st, fade_ms);
        state_save();
        ESP_LOGI(TAG, "light.set cool=%.1f warm=%.1f fade=%lu", st.cool, st.warm, (unsigned long)fade_ms);
    } else {
        ESP_LOGW(TAG, "call rejected: %s", err);
    }

    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "type", "result");
    cJSON_AddItemToObject(r, "call_id", cJSON_Duplicate(cJSON_GetObjectItem(msg, "call_id"), 1));
    cJSON_AddBoolToObject(r, "ok", !err[0]);
    cJSON_AddNullToObject(r, "say");
    cJSON_AddItemToObject(r, "data", state_json());
    if (err[0]) cJSON_AddStringToObject(r, "error", err); else cJSON_AddNullToObject(r, "error");
    send_json(r);
    if (!err[0]) send_state();
}

static void ws_event_handler(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    esp_websocket_event_data_t *d = event_data;
    if (id == WEBSOCKET_EVENT_CONNECTED) {
        ESP_LOGI(TAG, "peer link up");
        send_hello();
        return;
    }
    if (id != WEBSOCKET_EVENT_DATA || d->op_code != 1) return;
    if (d->payload_offset != 0 || d->data_len != d->payload_len) {
        ESP_LOGW(TAG, "dropping fragmented frame (%d bytes)", d->payload_len);  // shortcut: commands are tiny; reassemble if that changes
        return;
    }
    cJSON *msg = cJSON_ParseWithLength(d->data_ptr, d->data_len);
    const cJSON *type = cJSON_GetObjectItem(msg, "type");
    if (!cJSON_IsString(type)) {
        ESP_LOGW(TAG, "bad frame: %.*s", d->data_len, d->data_ptr);
    } else if (strcmp(type->valuestring, "welcome") == 0) {
        ESP_LOGI(TAG, "welcomed by Cadence");
        esp_ota_mark_app_valid_cancel_rollback();  // a reachable Cadence proves the image works
        send_state();
    } else if (strcmp(type->valuestring, "call") == 0) {
        handle_call(msg);
    } else if (strcmp(type->valuestring, "error") == 0) {
        ESP_LOGE(TAG, "Cadence error: %.*s", d->data_len, d->data_ptr);
    }
    cJSON_Delete(msg);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    // Light first: WiFi or Cadence being down must never leave the room dark.
    led_init();
    apply(state_load(), BOOT_FADE_MS);
    ESP_LOGI(TAG, "restored cool=%.1f warm=%.1f", s_state.cool, s_state.warm);

    wifi_init_sta();
    ota_check();

    esp_websocket_client_config_t ws_cfg = {.uri = CONFIG_LAMP_PEER_URL};
    s_ws = esp_websocket_client_init(&ws_cfg);
    esp_websocket_register_events(s_ws, WEBSOCKET_EVENT_ANY, ws_event_handler, NULL);
    esp_websocket_client_start(s_ws);  // reconnects on its own
}
