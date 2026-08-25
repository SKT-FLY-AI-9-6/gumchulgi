import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/dashboard.dart';
import '../state/settings.dart';
import '../theme.dart';

// 리디자인 시안 v1 — C. 시청 보호 설정 팔레트
const _violet = Color(0xFF8B5CF6);
const _pink = Color(0xFFF04B64);
const _sheetBg = Color(0xFF12121C);
const _cardBg = Color(0xFF171724);
const _stroke = Color(0xFF28283A);
const _grad = LinearGradient(colors: [_violet, _pink]);

class _GradSwitch extends StatelessWidget {
  final bool value;
  final ValueChanged<bool> onChanged;
  const _GradSwitch({required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => onChanged(!value),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        width: 46, height: 27,
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(14),
          gradient: value ? _grad : null,
          color: value ? null : const Color(0xFF33334A)),
        child: AnimatedAlign(
          duration: const Duration(milliseconds: 160),
          alignment: value ? Alignment.centerRight : Alignment.centerLeft,
          child: Container(width: 21, height: 21,
              decoration: const BoxDecoration(
                  shape: BoxShape.circle, color: Colors.white))),
      ),
    );
  }
}

class _SettingRow extends StatelessWidget {
  final String title, desc;
  final bool value;
  final ValueChanged<bool> onChanged;
  final bool divider;
  const _SettingRow({required this.title, required this.desc,
      required this.value, required this.onChanged, this.divider = true});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: BoxDecoration(border: divider
          ? const Border(bottom: BorderSide(
              color: Color(0x0FFFFFFF)))
          : null),
      child: Row(children: [
        Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
          Text(title, style: const TextStyle(
              fontSize: 14.5, fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text(desc, style: const TextStyle(
              fontSize: 11.5, color: AppColors.sub)),
        ])),
        _GradSwitch(value: value, onChanged: onChanged),
      ]),
    );
  }
}

void showSettingsSheet(BuildContext context) {
  showModalBottomSheet(
    context: context,
    backgroundColor: Colors.transparent,
    barrierColor: const Color(0x9E04040A),
    builder: (_) => Consumer(builder: (context, ref, _) {
      final s = ref.watch(settingsProvider).value;
      final n = ref.read(settingsProvider.notifier);
      final messenger = ScaffoldMessenger.of(context);
      void onSaveError(Object _) => messenger.showSnackBar(
          const SnackBar(content: Text('설정 저장 실패 — 다시 시도해주세요')));
      return Container(
        decoration: const BoxDecoration(
          color: _sheetBg,
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
          border: Border(top: BorderSide(color: _stroke))),
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
        child: SafeArea(top: false, child: s == null
            ? const SizedBox(height: 180)
            : Column(mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              Center(child: Container(width: 44, height: 5,
                  decoration: BoxDecoration(
                      color: const Color(0xFF3A3A4E),
                      borderRadius: BorderRadius.circular(3)))),
              const SizedBox(height: 16),
              const Text('시청 보호 설정', style: TextStyle(
                  fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 3),
              const Text('나에게 맞는 강도로 위험 자극을 조절하세요',
                  style: TextStyle(fontSize: 12, color: AppColors.sub)),
              const SizedBox(height: 8),
              _SettingRow(title: '필터 기능',
                  desc: '위험 구간을 보정본으로 재생',
                  value: s.filterOn,
                  onChanged: (v) =>
                      n.setFilter(v).catchError(onSaveError)),
              _SettingRow(title: '위험 구간 자동 스킵',
                  desc: '보정 불가 영상은 피드에서 제외',
                  value: s.autoSkip, divider: false,
                  onChanged: (v) =>
                      n.setAutoSkip(v).catchError(onSaveError)),
              const SizedBox(height: 12),
              InkWell(
                borderRadius: BorderRadius.circular(14),
                onTap: () {
                  Navigator.pop(context);
                  Navigator.push(context, MaterialPageRoute(
                      builder: (_) => const DashboardScreen()));
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 13),
                  decoration: BoxDecoration(
                      color: _cardBg,
                      border: Border.all(color: _stroke),
                      borderRadius: BorderRadius.circular(14)),
                  child: const Row(children: [
                    Expanded(child: Text('광 노출 대시보드 보기',
                        style: TextStyle(fontSize: 13.5,
                            fontWeight: FontWeight.w600))),
                    Text('›', style: TextStyle(
                        fontSize: 16, color: AppColors.sub)),
                  ]),
                ),
              ),
              const SizedBox(height: 10),
              const Center(child: Text(
                  '위험 노출은 일일 예산 300초 기준으로 집계됩니다',
                  style: TextStyle(
                      fontSize: 10.5, color: AppColors.sub))),
            ])),
      );
    }));
}
