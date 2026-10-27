// Copyright 2022 Manna Harbour
// https://github.com/manna-harbour/miryoku

#pragma once

// U_MT_L / U_MT_R mark left- and right-hand home-row mods in the layer data;
// both use the same behavior.
#define U_MT_L(MOD, TAP) &u_mt MOD TAP
#define U_MT_R(MOD, TAP) &u_mt MOD TAP
#define U_MT(MOD, TAP) &u_mt MOD TAP
#define U_LT(LAYER, TAP) &u_lt LAYER TAP
