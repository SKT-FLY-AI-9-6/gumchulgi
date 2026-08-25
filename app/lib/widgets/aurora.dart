import 'dart:math' as math;

import 'package:flutter/material.dart';

/// 리디자인 v2 "Ink & Aurora" 팔레트 (softreel_reimagined_v2)
class Aurora {
  static const ink0 = Color(0xFF0C0B13);
  static const ink1 = Color(0xFF14131C);
  static const ink2 = Color(0xFF1B1A26);
  static const line = Color(0xFF272635);
  static const teal = Color(0xFF5EEAD4);
  static const peri = Color(0xFF8B9DF8);
  static const rose = Color(0xFFFB8FA5);
  static const amber = Color(0xFFF5B85F);
  static const sub = Color(0xFF8E90A6);
  static const grad = LinearGradient(
      begin: Alignment.topLeft, end: Alignment.bottomRight,
      colors: [teal, peri, rose], stops: [0, .52, 1]);
}

/// 그라데이션 글자 ("Soft"Reel 워드마크용)
class GradText extends StatelessWidget {
  final String text;
  final TextStyle style;
  const GradText(this.text, {super.key, required this.style});
  @override
  Widget build(BuildContext context) => ShaderMask(
      shaderCallback: (r) => Aurora.grad.createShader(r),
      child: Text(text, style: style.copyWith(color: Colors.white)));
}

/// 오로라 그라데이션 채움 버튼
class AuroraButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;
  const AuroraButton({super.key, required this.label, this.onTap});
  @override
  Widget build(BuildContext context) => InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(17),
      child: Opacity(opacity: onTap == null ? .45 : 1, child: Container(
          height: 52, alignment: Alignment.center,
          decoration: BoxDecoration(
              gradient: Aurora.grad,
              borderRadius: BorderRadius.circular(17)),
          child: Text(label, style: const TextStyle(
              color: Aurora.ink0, fontSize: 14.5,
              fontWeight: FontWeight.w800)))));
}

/// 브랜드 심볼 = 할로 링. progress(0~1)만큼 그라데이션 호를 그린다.
/// colors 를 주면 해당 팔레트(예: v1 바이올렛-핑크)로 그린다.
class HaloRing extends StatelessWidget {
  final double size;
  final double progress;
  final double stroke;
  final Widget? center;
  final List<Color>? colors;
  final List<double>? stops;
  const HaloRing({super.key, required this.size, required this.progress,
      this.stroke = 9, this.center, this.colors, this.stops});
  @override
  Widget build(BuildContext context) => SizedBox(
      width: size, height: size,
      child: CustomPaint(
          painter: _RingPainter(progress.clamp(0, 1), stroke,
              colors ?? const [Aurora.teal, Aurora.peri, Aurora.rose],
              stops ?? const [0, .52, 1]),
          child: center == null ? null : Center(child: center)));
}

class _RingPainter extends CustomPainter {
  final double progress, stroke;
  final List<Color> colors;
  final List<double> stops;
  _RingPainter(this.progress, this.stroke, this.colors, this.stops);
  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = (size.shortestSide - stroke) / 2;
    final rect = Rect.fromCircle(center: c, radius: r);
    canvas.drawCircle(c, r, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = const Color(0xFF232233));
    if (progress > 0) {
      canvas.drawArc(rect, -math.pi / 2, 2 * math.pi * progress, false,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = stroke
            ..strokeCap = StrokeCap.round
            ..shader = SweepGradient(
                startAngle: -math.pi / 2,
                endAngle: 3 * math.pi / 2,
                colors: colors, stops: stops,
                transform: const GradientRotation(-math.pi / 2),
            ).createShader(rect));
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress || old.stroke != stroke ||
      old.colors != colors;
}

/// 카드 컨테이너 (ink1 배경 + line 테두리)
class InkCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const InkCard({super.key, required this.child,
      this.padding = const EdgeInsets.all(14)});
  @override
  Widget build(BuildContext context) => Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
          color: Aurora.ink1,
          border: Border.all(color: Aurora.line),
          borderRadius: BorderRadius.circular(20)),
      child: child);
}
