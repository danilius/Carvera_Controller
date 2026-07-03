#ifndef LV_CONF_H
#define LV_CONF_H

/*
 * Minimal LVGL v8 configuration for CYD pendant bring-up.
 * Expand this as UI complexity grows.
 */

#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 0

#define LV_MEM_CUSTOM 0
#define LV_MEM_SIZE (64U * 1024U)

#define LV_DISP_DEF_REFR_PERIOD 30
#define LV_INDEV_DEF_READ_PERIOD 30

#define LV_USE_LOG 0
#define LV_USE_ASSERT_NULL 1
#define LV_USE_ASSERT_MALLOC 1

/* We call lv_tick_inc() in loop(). */
#define LV_TICK_CUSTOM 0

/* Widgets used by current screen. */
#define LV_USE_LABEL 1

#endif /* LV_CONF_H */
