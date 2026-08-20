import 'package:flutter/material.dart';

class AppColors {
  static const bg = Color(0xFF0A0A0F);
  static const card = Color(0xFF14141B);
  static const blue = Color(0xFF3B6CFF);
  static const amber = Color(0xFFFFB020);
  static const red = Color(0xFFFF4D5E);
  static const sub = Color(0xFF9AA0AC);
}

final appTheme = ThemeData(
  brightness: Brightness.dark,
  scaffoldBackgroundColor: AppColors.bg,
  colorScheme: const ColorScheme.dark(
    primary: AppColors.blue, surface: AppColors.card, error: AppColors.red),
  useMaterial3: true,
);
