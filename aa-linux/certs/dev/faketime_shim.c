#define _GNU_SOURCE
#include <time.h>
#include <sys/time.h>
#include <dlfcn.h>

/* Fake date: 2021-06-15 12:00:00 UTC (when AACS cert was valid) */
static const time_t FAKE_EPOCH = 1623768000;

int gettimeofday(struct timeval *__restrict tv, void *__restrict tz) {
    int (*real_gettimeofday)(struct timeval *__restrict, void *__restrict) =
        dlsym(RTLD_NEXT, "gettimeofday");
    int ret = real_gettimeofday(tv, tz);
    if (tv) {
        tv->tv_sec = FAKE_EPOCH;
        tv->tv_usec = 0;
    }
    return ret;
}

time_t time(time_t *t) {
    if (t) *t = FAKE_EPOCH;
    return FAKE_EPOCH;
}

int clock_gettime(clockid_t clk_id, struct timespec *tp) {
    int (*real_clock_gettime)(clockid_t, struct timespec *) =
        dlsym(RTLD_NEXT, "clock_gettime");
    int ret = real_clock_gettime(clk_id, tp);
    if (clk_id == CLOCK_REALTIME && tp) {
        tp->tv_sec = FAKE_EPOCH;
        tp->tv_nsec = 0;
    }
    return ret;
}

int clock_getres(clockid_t clk_id, struct timespec *res) {
    int (*real_clock_getres)(clockid_t, struct timespec *) =
        dlsym(RTLD_NEXT, "clock_getres");
    int ret = real_clock_getres(clk_id, res);
    if (clk_id == CLOCK_REALTIME && res) {
        res->tv_sec = 0;
        res->tv_nsec = 1; /* 1 ns resolution */
    }
    return ret;
}
