import 'package:flutter/material.dart';

/// 리디자인 시안 v1 팔레트 (softreel_redesign_v1) — 바이올렛+핑크
class V1 {
  static const bg0 = Color(0xFF0B0B12);
  static const bg1 = Color(0xFF12121C);
  static const card = Color(0xFF171724);
  static const card2 = Color(0xFF1D1D2C);
  static const stroke = Color(0xFF28283A);
  static const violet = Color(0xFF8B5CF6);
  static const pink = Color(0xFFF04B64);
  static const green = Color(0xFF34D399);
  static const amber = Color(0xFFFFB020);
  static const cyan = Color(0xFF4DD8E6);
  static const sub = Color(0xFF9AA0AC);
  static const lavender = Color(0xFFB8A2FF);
  static const grad = LinearGradient(
      begin: Alignment.topLeft, end: Alignment.bottomRight,
      colors: [violet, pink]);
}

class V1Card extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const V1Card({super.key, required this.child,
      this.padding = const EdgeInsets.all(16)});
  @override
  Widget build(BuildContext context) => Container(
      width: double.infinity,
      padding: padding,
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
          color: V1.card,
          border: Border.all(color: V1.stroke),
          borderRadius: BorderRadius.circular(20)),
      child: child);
}

class V1Button extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;
  const V1Button({super.key, required this.label, this.onTap});
  @override
  Widget build(BuildContext context) => InkWell(
      onTap: onTap, borderRadius: BorderRadius.circular(16),
      child: Container(height: 50, alignment: Alignment.center,
          decoration: BoxDecoration(
              gradient: V1.grad,
              borderRadius: BorderRadius.circular(16),
              boxShadow: [BoxShadow(
                  color: V1.violet.withValues(alpha: .4),
                  blurRadius: 20, offset: const Offset(0, 6))]),
          child: Text(label, style: const TextStyle(color: Colors.white,
              fontSize: 15, fontWeight: FontWeight.w700))));
}
