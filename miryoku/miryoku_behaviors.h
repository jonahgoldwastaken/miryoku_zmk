// Copyright 2022 Manna Harbour
// https://github.com/manna-harbour/miryoku

#pragma once

#if defined(MIRYOKU_TIMELESS_HRM)
// Shift gets its own behavior (shorter idle window), selected by modifier.
#define U_MT_L(MOD, TAP) U_MT_L_SEL_##MOD(MOD, TAP)
#define U_MT_R(MOD, TAP) U_MT_R_SEL_##MOD(MOD, TAP)
#define U_MT_L_SEL_LSHFT(MOD, TAP) &u_mt_l_shift MOD TAP
#define U_MT_R_SEL_LSHFT(MOD, TAP) &u_mt_r_shift MOD TAP
#define U_MT_L_SEL_LGUI(MOD, TAP) &u_mt_l MOD TAP
#define U_MT_R_SEL_LGUI(MOD, TAP) &u_mt_r MOD TAP
#define U_MT_L_SEL_LALT(MOD, TAP) &u_mt_l MOD TAP
#define U_MT_R_SEL_LALT(MOD, TAP) &u_mt_r MOD TAP
#define U_MT_L_SEL_LCTRL(MOD, TAP) &u_mt_l MOD TAP
#define U_MT_R_SEL_LCTRL(MOD, TAP) &u_mt_r MOD TAP
#define U_MT_L_SEL_RALT(MOD, TAP) &u_mt_l MOD TAP
#define U_MT_R_SEL_RALT(MOD, TAP) &u_mt_r MOD TAP
#else
#define U_MT_L(MOD, TAP) &u_mt MOD TAP
#define U_MT_R(MOD, TAP) &u_mt MOD TAP
#endif
#define U_MT(MOD, TAP) &u_mt MOD TAP
#if defined(MIRYOKU_TIMELESS_HRM)
// Layer-taps are selected per layer: Sym/Num/Fun are chorded mid-typing
// (":" in vim, "(", digits), so they use the faster u_lt_fast; the rest keep
// the typing-protected u_lt.
#define U_LT(LAYER, TAP) U_LT_SEL_##LAYER(LAYER, TAP)
#define U_LT_SEL_U_SYM(LAYER, TAP) &u_lt_fast LAYER TAP
#define U_LT_SEL_U_NUM(LAYER, TAP) &u_lt_fast LAYER TAP
#define U_LT_SEL_U_FUN(LAYER, TAP) &u_lt_fast LAYER TAP
#define U_LT_SEL_U_NAV(LAYER, TAP) &u_lt LAYER TAP
#define U_LT_SEL_U_MOUSE(LAYER, TAP) &u_lt LAYER TAP
#define U_LT_SEL_U_MEDIA(LAYER, TAP) &u_lt LAYER TAP
#define U_LT_SEL_U_BUTTON(LAYER, TAP) &u_lt LAYER TAP
#else
#define U_LT(LAYER, TAP) &u_lt LAYER TAP
#endif
