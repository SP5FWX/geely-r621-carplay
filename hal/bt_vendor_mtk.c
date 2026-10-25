/*
 * bt_vendor_mtk.c — minimal MT6620 vendor library for the AOSP 5.1 Bluedroid HAL.
 *
 * Why this exists
 * ---------------
 * The R621 head unit ships a private Barrot/IVT Bluetooth stack that does not
 * expose Android's BluetoothAdapter. To use DiPlay we replace the host stack
 * with AOSP Bluedroid, but Bluedroid still needs a vendor library to drive the
 * MT6620 over its H4 UART (/dev/stpbt). This file is that vendor library.
 *
 * ABI notes (Android 5.1, 32-bit)
 * ------------------------------
 *  - Bluedroid resolves the *object* BLUETOOTH_VENDOR_LIB_INTERFACE, not a
 *    bt_vendor_get_interface() function.
 *  - The callback table layout below must match
 *    hardware/libhardware/include/hardware/bt_vendor.h exactly.
 *  - USERIAL_OPEN hands us int fds[4] (CMD/ACL/SCO/EVT). MT6620 is a single
 *    H4 port, so all four entries receive the same fd.
 *  - FW_CFG must invoke fwcfg_cb() or Bluedroid aborts with
 *    preload_wait_timeout after 5 seconds.
 *
 * Build
 * -----
 *   ./build.sh /path/to/arm-linux-gnueabi-gcc
 *   (-Wl,--hash-style=both is mandatory on Android 5.1)
 *
 * License: Apache-2.0
 */

#include <stddef.h>
#include <string.h>
#include <fcntl.h>

extern int open(const char *path, int flags, ...);
extern int close(int fd);
extern int write(int fd, const void *buf, size_t count);
extern long read(int fd, void *buf, size_t count);
extern int __android_log_print(int prio, const char *tag, const char *fmt, ...);

#define LOGI(...) __android_log_print(4, "bt_vendor_mtk", __VA_ARGS__)
#define LOGE(...) __android_log_print(6, "bt_vendor_mtk", __VA_ARGS__)

typedef unsigned char  uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int   uint32_t;

/* ---- Android 5.1 bt_vendor.h ------------------------------------------- */

typedef enum {
    BT_VND_OP_RESULT_SUCCESS = 0,
    BT_VND_OP_RESULT_FAIL    = 1
} bt_vendor_op_result_t;

typedef void (*cfg_result_cb)(bt_vendor_op_result_t result);
typedef void *(*malloc_cb)(int size);
typedef void (*mdealloc_cb)(void *p_buf);
typedef void (*tINT_CMD_CBACK)(void *p_mem);
typedef uint8_t (*cmd_xmit_cb)(uint16_t opcode, void *p_buf, tINT_CMD_CBACK p_cback);

typedef struct {
    size_t          size;
    cfg_result_cb   fwcfg_cb;
    cfg_result_cb   scocfg_cb;
    cfg_result_cb   lpm_cb;
    cfg_result_cb   audio_state_cb;
    malloc_cb       alloc;
    mdealloc_cb     dealloc;
    cmd_xmit_cb     xmit_cb;
    cfg_result_cb   epilog_cb;
} bt_vendor_callbacks_t;

#define BT_VND_OP_POWER_CTRL            0
#define BT_VND_OP_FW_CFG                1
#define BT_VND_OP_SCO_CFG               2
#define BT_VND_OP_USERIAL_OPEN          3
#define BT_VND_OP_USERIAL_CLOSE         4
#define BT_VND_OP_GET_LPM_IDLE_TIMEOUT  5
#define BT_VND_OP_LPM_SET_MODE          6
#define BT_VND_OP_LPM_WAKE_SET_STATE    7
#define BT_VND_OP_SET_AUDIO_STATE       8
#define BT_VND_OP_EPILOG                9

typedef struct {
    size_t size;
    int  (*init)(const bt_vendor_callbacks_t *p_cb, unsigned char *local_bdaddr);
    int  (*op)(int op, void *p_data);
    void (*cleanup)(void);
} bt_vendor_interface_t;

/* ---- configuration ----------------------------------------------------- */

/* Candidate UART nodes, tried in order. Adjust for non-MT6620 hardware. */
static const char *g_devs[] = {
    "/dev/stpbt",
    "/dev/ttyMT0",
    "/dev/ttyMT1",
    "/dev/ttyMT2",
    NULL
};

/* Optional BD_ADDR override, one address per line:
 *   AA:BB:CC:DD:EE:FF
 * Written by tools/deploy_hal.py. If absent, the chip keeps its factory
 * address, which may differ from what the vehicle recorded at first pairing.
 */
#define BDADDR_PATH "/data/local/etc/bt_bdaddr"

static const bt_vendor_callbacks_t *g_cb = NULL;
static int g_fd = -1;
static unsigned char g_bdaddr[6];
static int  g_bdaddr_valid = 0;

/* ---- helpers ----------------------------------------------------------- */

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* Parse "AA:BB:CC:DD:EE:FF" into 6 bytes (human order). */
static int parse_bdaddr(const char *s, unsigned char out[6])
{
    int i;
    for (i = 0; i < 6; i++) {
        int hi, lo;
        if (!s || !s[0]) return -1;
        hi = hex_nibble(s[0]);
        lo = hex_nibble(s[1]);
        if (hi < 0 || lo < 0) return -1;
        out[i] = (unsigned char)((hi << 4) | lo);
        s += 2;
        if (i < 5) {
            if (*s != ':' && *s != '-') return -1;
            s++;
        }
    }
    return 0;
}

static void load_bdaddr(void)
{
    char buf[64];
    int fd, n;

#ifdef BT_BDADDR_DEFAULT
    if (!g_bdaddr_valid && parse_bdaddr(BT_BDADDR_DEFAULT, g_bdaddr) == 0) {
        g_bdaddr_valid = 1;
    }
#endif

    fd = open(BDADDR_PATH, O_RDONLY);
    if (fd < 0) {
        LOGI("no %s, using %s", BDADDR_PATH,
             g_bdaddr_valid ? "compile-time address" : "chip factory address");
        return;
    }
    n = (int)read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return;
    buf[n] = '\0';

    /* strip trailing whitespace/newline */
    while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r' ||
                     buf[n - 1] == ' '  || buf[n - 1] == '\t')) {
        buf[--n] = '\0';
    }
    if (parse_bdaddr(buf, g_bdaddr) == 0) {
        g_bdaddr_valid = 1;
        LOGI("bdaddr from config: %s", buf);
    } else {
        LOGE("invalid bdaddr in %s: %s", BDADDR_PATH, buf);
    }
}

/* MTK vendor command 0xFC1A: set local BD_ADDR.
 * H4 frame: type(1) + opcode(2, LE) + plen(1) + params(6, LSB first)
 */
static void send_set_bdaddr(void)
{
    unsigned char cmd[10];
    int n;

    if (!g_bdaddr_valid || g_fd < 0) return;

    cmd[0] = 0x01;   /* H4: HCI Command */
    cmd[1] = 0x1A;   /* OCF */
    cmd[2] = 0xFC;   /* OGF 0x3F */
    cmd[3] = 0x06;   /* parameter length */
    /* MTK expects the address least-significant byte first */
    cmd[4] = g_bdaddr[5];
    cmd[5] = g_bdaddr[4];
    cmd[6] = g_bdaddr[3];
    cmd[7] = g_bdaddr[2];
    cmd[8] = g_bdaddr[1];
    cmd[9] = g_bdaddr[0];

    n = write(g_fd, cmd, sizeof(cmd));
    if (n == (int)sizeof(cmd)) {
        LOGI("set_bdaddr %02X:%02X:%02X:%02X:%02X:%02X ok",
             g_bdaddr[0], g_bdaddr[1], g_bdaddr[2],
             g_bdaddr[3], g_bdaddr[4], g_bdaddr[5]);
    } else {
        LOGE("set_bdaddr write=%d", n);
    }
}

/* ---- vendor interface -------------------------------------------------- */

static int vnd_init(const bt_vendor_callbacks_t *p_cb, unsigned char *local_bdaddr)
{
    int i;

    g_cb = p_cb;
    LOGI("init cb_size=%d fwcfg=%p", p_cb ? (int)p_cb->size : -1,
         p_cb ? (void *)p_cb->fwcfg_cb : NULL);

    load_bdaddr();

    /* Let Bluedroid know which address we will program into the chip. */
    if (local_bdaddr && g_bdaddr_valid) {
        for (i = 0; i < 6; i++) local_bdaddr[i] = g_bdaddr[i];
        LOGI("init bdaddr=%02X:%02X:%02X:%02X:%02X:%02X",
             g_bdaddr[0], g_bdaddr[1], g_bdaddr[2],
             g_bdaddr[3], g_bdaddr[4], g_bdaddr[5]);
    }
    return 0;
}

static int vnd_op(int op, void *p)
{
    switch (op) {
    case BT_VND_OP_POWER_CTRL:
        return 0;

    case BT_VND_OP_FW_CFG:
        /* No firmware download needed: the MT6620 firmware is already loaded
         * by the platform (wmt_loader). Just complete the handshake. */
        if (g_cb && g_cb->fwcfg_cb)
            g_cb->fwcfg_cb(BT_VND_OP_RESULT_SUCCESS);
        return 0;

    case BT_VND_OP_SCO_CFG:
        if (g_cb && g_cb->scocfg_cb)
            g_cb->scocfg_cb(BT_VND_OP_RESULT_SUCCESS);
        return 0;

    case BT_VND_OP_USERIAL_OPEN: {
        int i, fd = -1;

        for (i = 0; g_devs[i]; i++) {
            fd = open(g_devs[i], O_RDWR | O_NOCTTY);
            LOGI("USERIAL_OPEN %s fd=%d", g_devs[i], fd);
            if (fd >= 0) break;
        }
        if (fd < 0) {
            LOGE("USERIAL_OPEN failed: no usable UART node");
            return 0;
        }

        if (p) {
            int *fds = (int *)p;
            int ch;
            for (ch = 0; ch < 4; ch++) fds[ch] = fd;
        }

        g_fd = fd;
        send_set_bdaddr();
        return 1;
    }

    case BT_VND_OP_USERIAL_CLOSE:
        if (g_fd >= 0) {
            close(g_fd);
            g_fd = -1;
        }
        return 1;

    case BT_VND_OP_GET_LPM_IDLE_TIMEOUT:
        if (p) *((uint32_t *)p) = 0;
        return 0;

    case BT_VND_OP_LPM_SET_MODE:
        if (g_cb && g_cb->lpm_cb)
            g_cb->lpm_cb(BT_VND_OP_RESULT_SUCCESS);
        return 0;

    case BT_VND_OP_SET_AUDIO_STATE:
        if (g_cb && g_cb->audio_state_cb)
            g_cb->audio_state_cb(BT_VND_OP_RESULT_SUCCESS);
        return 0;

    case BT_VND_OP_EPILOG:
        if (g_cb && g_cb->epilog_cb)
            g_cb->epilog_cb(BT_VND_OP_RESULT_SUCCESS);
        return 0;

    case BT_VND_OP_LPM_WAKE_SET_STATE:
    default:
        return 0;
    }
}

static void vnd_cleanup(void)
{
    if (g_fd >= 0) {
        close(g_fd);
        g_fd = -1;
    }
}

/* Must be a global object with exactly this name. */
const bt_vendor_interface_t BLUETOOTH_VENDOR_LIB_INTERFACE = {
    sizeof(bt_vendor_interface_t),
    vnd_init,
    vnd_op,
    vnd_cleanup
};
