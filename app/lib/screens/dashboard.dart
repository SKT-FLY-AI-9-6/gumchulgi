import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/settings.dart';
import '../theme.dart';

const _statusKo = {'good': '양호', 'caution': '주의', 'warning': '경고'};
const _statusColor = {
  'good': Colors.greenAccent, 'caution': AppColors.amber,
  'warning': AppColors.red};
const _stimKo = [
  ('flash', '고휘도 플래시', AppColors.amber),
  ('red', '포화 적색', AppColors.red),
  ('pattern', '정적 패턴', Colors.cyanAccent),
  ('cut', '화면 전환', Color(0xFF8A7BFF)),
];

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('광 노출 대시보드')),
      body: FutureBuilder(
        future: Future.wait([api.dashboardToday(), api.dashboardWeekly()]),
        builder: (context, snap) {
          if (snap.hasError) {
            return const Center(child: Text('불러오기 실패'));
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final today = snap.data![0] as DashboardToday;
          final weekly = snap.data![1] as Weekly;
          final min = (today.exposureS ~/ 60);
          final sec = (today.exposureS % 60).round();
          return ListView(padding: const EdgeInsets.all(16), children: [
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('오늘의 광 자극 노출',
                  style: TextStyle(color: AppColors.sub)),
              Row(children: [
                Icon(Icons.warning_amber,
                    color: _statusColor[today.status]),
                const SizedBox(width: 6),
                Text(_statusKo[today.status] ?? today.status,
                    style: TextStyle(fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: _statusColor[today.status])),
              ]),
              const SizedBox(height: 6),
              Text('오늘 위험 영상 ${today.riskyViews}회 · '
                  '위험 노출 시간 $min분 $sec초'),
              Text('일간 임계치(80%) 대비 누적 ${today.percent}%',
                  style: const TextStyle(color: AppColors.sub)),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('광 자극 노출도'),
              const SizedBox(height: 12),
              SizedBox(height: 160, child: _curveChart(today)),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('위험 영상 노출 수 (주간)'),
              Text('오늘 ${today.riskyViews}회 · 주간 평균 ${weekly.avg}회',
                  style: const TextStyle(
                      color: AppColors.sub, fontSize: 12)),
              const SizedBox(height: 12),
              SizedBox(height: 140, child: _weekChart(weekly)),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('오늘 노출된 자극'),
              const SizedBox(height: 8),
              for (final (key, label, color) in _stimKo)
                Padding(padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(children: [
                  SizedBox(width: 110, child: Text(label,
                      style: const TextStyle(fontSize: 13))),
                  Expanded(child: LinearProgressIndicator(
                      value: ((today.stimulus[key] ?? 0) / 10).clamp(0, 1),
                      color: color,
                      backgroundColor: AppColors.bg, minHeight: 6)),
                  SizedBox(width: 44, child: Text(
                      '  ${today.stimulus[key] ?? 0}회',
                      style: const TextStyle(fontSize: 13))),
                ])),
            ])),
            const SizedBox(height: 8),
            FilledButton(
                onPressed: () {
                  ref.read(settingsProvider.notifier).setFilter(true);
                  Navigator.pop(context);
                },
                child: const Text('필터 켜기')),
          ]);
        }),
    );
  }

  Widget _card(Widget child) => Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: AppColors.card,
          borderRadius: BorderRadius.circular(16)),
      child: child);

  Widget _curveChart(DashboardToday t) {
    final spots = [
      const FlSpot(0, 0),
      ...t.curve.map((c) => FlSpot(c.hour.toDouble(), c.percent)),
    ];
    return LineChart(LineChartData(
      minX: 0, maxX: 24, minY: 0,
      maxY: [100.0, t.percent + 10].reduce((a, b) => a > b ? a : b),
      titlesData: const FlTitlesData(
          leftTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true, reservedSize: 36)),
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true, interval: 6)),
          topTitles: AxisTitles(), rightTitles: AxisTitles()),
      extraLinesData: ExtraLinesData(horizontalLines: [
        HorizontalLine(y: 80, color: AppColors.red, strokeWidth: 1,
            dashArray: [6, 4]),
      ]),
      lineBarsData: [LineChartBarData(
          spots: spots, color: AppColors.red, isCurved: false,
          belowBarData: BarAreaData(show: true,
              color: AppColors.red.withValues(alpha: .15)))],
    ));
  }

  Widget _weekChart(Weekly w) {
    const days = ['월', '화', '수', '목', '금', '토', '일'];
    return BarChart(BarChartData(
      titlesData: FlTitlesData(
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true,
              getTitlesWidget: (v, _) {
                final d = DateTime.parse(w.days[v.toInt()].date);
                return Text(days[d.weekday - 1],
                    style: const TextStyle(fontSize: 11));
              })),
          leftTitles: const AxisTitles(),
          topTitles: const AxisTitles(), rightTitles: const AxisTitles()),
      barGroups: [
        for (var i = 0; i < w.days.length; i++)
          BarChartGroupData(x: i, barRods: [BarChartRodData(
              toY: w.days[i].riskyViews.toDouble(),
              color: i == w.days.length - 1
                  ? AppColors.blue : AppColors.blue.withValues(alpha: .4),
              width: 16,
              borderRadius: BorderRadius.circular(4))]),
      ],
    ));
  }
}
