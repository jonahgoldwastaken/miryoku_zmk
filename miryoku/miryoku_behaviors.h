// Copyright 2022 Manna Harbour
// https://github.com/manna-harbour/miryoku

#pragma once

#if defined(MIRYOKU_TIMELESS_HRM)
#define U_MT_L(MOD, TAP) &u_mt_l MOD TAP
#define U_MT_R(MOD, TAP) &u_mt_r MOD TAP
#else
#define U_MT_L(MOD, TAP) &u_mt MOD TAP
#define U_MT_R(MOD, TAP) &u_mt MOD TAP
#endif
#define U_MT(MOD, TAP) &u_mt MOD TAP
#define U_LT(LAYER, TAP) &u_lt LAYER TAP
