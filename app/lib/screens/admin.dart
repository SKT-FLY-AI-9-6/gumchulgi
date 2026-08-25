import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/auth.dart';
import '../theme.dart';

/// 관리자 운영 대시보드 — 필터 ON/OFF 시청 행동 비교와 B2C 비용 환산.
class AdminScreen extends ConsumerStatefulWidget {
  const AdminScreen({super.key});
  @override
  ConsumerState<AdminScreen> createState() => _AdminState();
}

class _AdminState extends ConsumerState<AdminScreen> {
  double _cpm = 5000;
  late Future<AdminMetrics> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(apiProvider).adminMetrics(cpm: _cpm);
  }

  void _reload() => setState(() {
        _future = ref.read(apiProvider).adminMetrics(cpm: _cpm);
      });

  String _won(int v) {
    final s = v.toString();
    final b = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
      b.write(s[i]);
    }
    return '$b원';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('운영 대시보드 (관리자)'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _reload),
        IconButton(icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authProvider.notifier).logout()),
      ]),
      body: FutureBuilder(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) {
            return const Center(child: Text('불러오기 실패 — 관리자 계정인지 확인'));
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final m = snap.data as AdminMetrics;
          final on = m.filtered, off = m.original;
          return ListView(padding: const EdgeInsets.all(16), children: [
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('필터 ON vs OFF — 위험 영상 시청 행동',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              Text('위험 영상 노출 ${m.totalRiskyViews}회 '
                  '(보정본 ${on.views} · 원본 ${off.views})',
                  style: const TextStyle(
                      color: AppColors.sub, fontSize: 12)),
              const SizedBox(height: 16),
              SizedBox(height: 170, child: _compareChart(on, off)),
              const SizedBox(height: 8),
              Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                _legend(AppColors.blue, '필터 ON (보정본)'),
                const SizedBox(width: 16),
                _legend(AppColors.amber, '필터 OFF (원본)'),
              ]),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('필터 효과',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              _kv('시청 유지율',
                  '+${m.watchRatioPp.toStringAsFixed(1)}%p',
                  Colors.greenAccent),
              _kv('이탈율 감소',
                  '-${m.bouncePp.toStringAsFixed(1)}%p', Colors.greenAccent),
              _kv('지켜낸 시청시간 (실측)',
                  '${m.keptMinActual.toStringAsFixed(1)}분', null),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('B2C 비용 환산',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              Text('이탈 방지로 지켜낸 시청시간 → 광고 노출 환산 '
                  '(분당 1회 · CPM ${_won(m.cpm.round())})',
                  style: const TextStyle(
                      color: AppColors.sub, fontSize: 12)),
              const SizedBox(height: 12),
              _kv('현재 데이터 기준 절약', _won(m.savedKrwActual), null),
              _kv('위험 노출 1만 회당', _won(m.savedKrwPer10k),
                  AppColors.blue),
              _kv('위험 노출 100만 회당', _won(m.savedKrwPer1m),
                  AppColors.blue),
              const SizedBox(height: 12),
              Row(children: [
                const Text('CPM ', style: TextStyle(fontSize: 13)),
                Expanded(child: Slider(
                    value: _cpm, min: 1000, max: 20000, divisions: 19,
                    label: _won(_cpm.round()),
                    onChanged: (v) => setState(() => _cpm = v),
                    onChangeEnd: (_) => _reload())),
              ]),
              Text('가정: 평균 영상 ${m.avgDurationS.toStringAsFixed(0)}초 · '
                  '이탈 = 절반 미만 시청 · 데모용 추정 모델',
                  style: const TextStyle(
                      color: AppColors.sub, fontSize: 11)),
            ])),
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

  Widget _legend(Color c, String t) => Row(children: [
        Container(width: 10, height: 10, color: c),
        const SizedBox(width: 4),
        Text(t, style: const TextStyle(fontSize: 11, color: AppColors.sub)),
      ]);

  Widget _kv(String k, String v, Color? color) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Expanded(child: Text(k, style: const TextStyle(fontSize: 13))),
        Text(v, style: TextStyle(fontSize: 15,
            fontWeight: FontWeight.bold, color: color)),
      ]));

  Widget _compareChart(AdminGroup on, AdminGroup off) {
    BarChartGroupData g(int x, double onV, double offV) =>
        BarChartGroupData(x: x, barsSpace: 6, barRods: [
          BarChartRodData(toY: onV * 100, color: AppColors.blue, width: 22,
              borderRadius: BorderRadius.circular(3)),
          BarChartRodData(toY: offV * 100, color: AppColors.amber, width: 22,
              borderRadius: BorderRadius.circular(3)),
        ]);
    const labels = ['시청 유지율', '이탈율'];
    return BarChart(BarChartData(
      maxY: 100,
      titlesData: FlTitlesData(
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true,
              getTitlesWidget: (v, _) => Text(labels[v.toInt()],
                  style: const TextStyle(fontSize: 12)))),
          leftTitles: const AxisTitles(sideTitles: SideTitles(
              showTitles: true, reservedSize: 34)),
          topTitles: const AxisTitles(), rightTitles: const AxisTitles()),
      barGroups: [
        g(0, on.avgWatchRatio, off.avgWatchRatio),
        g(1, on.bounceRate, off.bounceRate),
      ],
    ));
  }
}
