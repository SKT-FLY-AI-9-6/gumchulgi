import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/settings.dart';
import '../widgets/aurora.dart' show HaloRing;
import '../widgets/brand_v1.dart';

const _statusKo = {'good': '양호', 'caution': '주의', 'warning': '경고'};
const _statusColor = {
  'good': V1.green, 'caution': V1.amber, 'warning': V1.pink};
const _stimKo = [
  ('flash', '고휘도 플래시', V1.amber),
  ('red', '포화 적색', V1.pink),
  ('pattern', '정적 패턴', V1.cyan),
  ('cut', '화면 전환', V1.violet),
];

/// 시안 v1 — B. 광 노출 대시보드
class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(apiProvider);
    final filterOn = ref.watch(settingsProvider).value?.filterOn ?? true;
    return Scaffold(
      backgroundColor: V1.bg0,
      appBar: AppBar(backgroundColor: V1.bg0,
          title: const Text('광 노출 대시보드',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700))),
      body: SafeArea(top: false, child: FutureBuilder(
        future: Future.wait([api.dashboardToday(), api.dashboardWeekly()]),
        builder: (context, snap) {
          if (snap.hasError) {
            return const Center(child: Text('불러오기 실패',
                style: TextStyle(color: V1.sub)));
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final today = snap.data![0] as DashboardToday;
          final weekly = snap.data![1] as Weekly;
          final min = today.exposureS ~/ 60;
          final sec = (today.exposureS % 60).round();
          return ListView(padding: const EdgeInsets.all(20), children: [
            // 히어로 — 링 게이지 + 스탯
            V1Card(child: Row(children: [
              HaloRing(size: 124, progress: today.percent / 100,
                  stroke: 12,
                  colors: const [V1.violet, V1.pink],
                  stops: const [0, 1],
                  center: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text('${today.percent.round()}%',
                        style: const TextStyle(fontSize: 27,
                            fontWeight: FontWeight.w800)),
                    Text(_statusKo[today.status] ?? today.status,
                        style: TextStyle(fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: _statusColor[today.status])),
                  ])),
              const SizedBox(width: 18),
              Expanded(child: Column(children: [
                _hstat('오늘 위험 영상', '${today.riskyViews}회'),
                const SizedBox(height: 9),
                _hstat('위험 노출 시간', '$min분 $sec초'),
                const SizedBox(height: 9),
                _hstat('일일 예산 ${today.budgetS}초',
                    '${today.exposureS.round()}초 사용'),
                const SizedBox(height: 6),
                ClipRRect(borderRadius: BorderRadius.circular(3),
                    child: LinearProgressIndicator(
                        value: (today.exposureS / today.budgetS)
                            .clamp(0.0, 1.0),
                        minHeight: 6, backgroundColor: V1.bg0,
                        valueColor: const AlwaysStoppedAnimation(V1.violet))),
              ])),
            ])),
            // 오늘 누적 노출 추이
            V1Card(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('오늘 누적 노출 추이', style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w700)),
              const Text('80% 도달 시 경고', style: TextStyle(
                  fontSize: 11, color: V1.sub)),
              const SizedBox(height: 12),
              SizedBox(height: 150, child: _curveChart(today)),
            ])),
            // 주간 위험 노출
            V1Card(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Text('주간 위험 노출', style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w700)),
                const SizedBox(width: 8),
                Text('오늘 ${today.riskyViews}회 · 주 평균 ${weekly.avg}회',
                    style: const TextStyle(fontSize: 11, color: V1.sub)),
              ]),
              const SizedBox(height: 12),
              SizedBox(height: 130, child: _weekChart(weekly)),
            ])),
            // 오늘 노출된 자극 (2열 칩)
            V1Card(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('오늘 노출된 자극', style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              GridView.count(
                  crossAxisCount: 2, shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  mainAxisSpacing: 8, crossAxisSpacing: 8,
                  childAspectRatio: 3.9,
                  children: [
                for (final (key, label, color) in _stimKo)
                  Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(color: V1.card2,
                          borderRadius: BorderRadius.circular(14)),
                      child: Row(children: [
                        Container(width: 9, height: 9,
                            decoration: BoxDecoration(color: color,
                                borderRadius: BorderRadius.circular(3))),
                        const SizedBox(width: 9),
                        Expanded(child: Text(label, style: const TextStyle(
                            fontSize: 11.5, color: V1.sub))),
                        Text('${today.stimulus[key] ?? 0}회',
                            style: const TextStyle(fontSize: 13,
                                fontWeight: FontWeight.w700)),
                      ])),
              ]),
            ])),
            if (!filterOn) ...[
              const SizedBox(height: 2),
              V1Button(label: '필터 켜고 안전하게 보기', onTap: () {
                final messenger = ScaffoldMessenger.of(context);
                ref.read(settingsProvider.notifier).setFilter(true)
                    .catchError((_) => messenger.showSnackBar(
                        const SnackBar(content:
                            Text('설정 저장 실패 — 다시 시도해주세요'))));
                Navigator.pop(context);
              }),
              const SizedBox(height: 16),
            ],
          ]);
        })),
    );
  }

  Widget _hstat(String l, String v) => Row(children: [
    Expanded(child: Text(l, style: const TextStyle(
        fontSize: 12.5, color: V1.sub))),
    Text(v, style: const TextStyle(
        fontSize: 12.5, fontWeight: FontWeight.w600)),
  ]);

  Widget _curveChart(DashboardToday t) {
    final spots = [
      const FlSpot(0, 0),
      ...t.curve.map((c) => FlSpot(c.hour.toDouble(), c.percent)),
    ];
    return LineChart(LineChartData(
      minX: 0, maxX: 24, minY: 0,
      maxY: [100.0, t.percent + 10].reduce((a, b) => a > b ? a : b),
      gridData: const FlGridData(show: false),
      borderData: FlBorderData(show: false),
      titlesData: const FlTitlesData(
          leftTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true, reservedSize: 34)),
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true, interval: 6)),
          topTitles: AxisTitles(), rightTitles: AxisTitles()),
      extraLinesData: ExtraLinesData(horizontalLines: [
        HorizontalLine(y: 80, color: V1.pink, strokeWidth: 1,
            dashArray: [5, 4]),
      ]),
      lineBarsData: [LineChartBarData(
          spots: spots, color: V1.violet, isCurved: false,
          barWidth: 2.5, dotData: const FlDotData(show: false),
          belowBarData: BarAreaData(show: true,
              color: V1.violet.withValues(alpha: .16)))],
    ));
  }

  Widget _weekChart(Weekly w) {
    const days = ['월', '화', '수', '목', '금', '토', '일'];
    return BarChart(BarChartData(
      gridData: const FlGridData(show: false),
      borderData: FlBorderData(show: false),
      titlesData: FlTitlesData(
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true,
              getTitlesWidget: (v, meta) {
                final d = DateTime.parse(w.days[v.toInt()].date);
                final last = v.toInt() == w.days.length - 1;
                return Text(days[d.weekday - 1], style: TextStyle(
                    fontSize: 11,
                    fontWeight: last ? FontWeight.w700 : FontWeight.w400,
                    color: last ? V1.lavender : V1.sub));
              })),
          leftTitles: const AxisTitles(),
          topTitles: const AxisTitles(), rightTitles: const AxisTitles()),
      barGroups: [
        for (var i = 0; i < w.days.length; i++)
          BarChartGroupData(x: i, barRods: [BarChartRodData(
              toY: w.days[i].riskyViews.toDouble(),
              gradient: i == w.days.length - 1
                  ? const LinearGradient(colors: [V1.violet, V1.pink],
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter)
                  : null,
              color: i == w.days.length - 1 ? null : const Color(0xFF33334A),
              width: 18,
              borderRadius: BorderRadius.circular(5))]),
      ],
    ));
  }
}
