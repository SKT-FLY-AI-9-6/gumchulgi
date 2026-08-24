import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/banner.dart';
import '../screens/dashboard.dart';
import '../state/exposure.dart';
import '../state/settings.dart';
import 'brand_v1.dart';

/// 시안 v1 톤으로 통일한 경고 배너 — 카드/버튼이 설정 시트·대시보드와
/// 같은 문법(스트로크 카드 + 그라데이션 주 버튼 + 고스트 보조 버튼).
class WarningBanner extends ConsumerWidget {
  const WarningBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exposure = ref.watch(exposureProvider);
    final settings = ref.watch(settingsProvider).value;
    final dismissedAt = ref.watch(bannerDismissProvider);
    if (settings == null ||
        !shouldShowBanner(percent: exposure?.percent,
            filterOn: settings.filterOn, dismissedAt: dismissedAt)) {
      return const SizedBox.shrink();
    }
    final messenger = ScaffoldMessenger.of(context);
    return Positioned(top: 56, left: 12, right: 12, child: Material(
      color: Colors.transparent,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
            color: V1.card,
            border: Border.all(color: V1.amber.withValues(alpha: .55)),
            borderRadius: BorderRadius.circular(20),
            boxShadow: const [BoxShadow(
                color: Color(0x66000000), blurRadius: 18,
                offset: Offset(0, 6))]),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(width: 34, height: 34,
                  decoration: BoxDecoration(
                      color: V1.amber.withValues(alpha: .14),
                      borderRadius: BorderRadius.circular(11)),
                  child: const Icon(Icons.warning_amber,
                      size: 19, color: V1.amber)),
              const SizedBox(width: 10),
              const Expanded(child: Padding(
                  padding: EdgeInsets.only(top: 1),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    Text('위험 영상 노출이 많아요',
                        style: TextStyle(fontSize: 13.5,
                            fontWeight: FontWeight.w700)),
                    SizedBox(height: 2),
                    Text('필터를 켜면 안전하게 볼 수 있어요',
                        style: TextStyle(fontSize: 11.5, color: V1.sub)),
                  ]))),
              SizedBox(width: 28, height: 28, child: IconButton(
                  padding: EdgeInsets.zero,
                  tooltip: '닫기',
                  icon: const Icon(Icons.close, size: 18, color: V1.sub),
                  onPressed: () => ref.read(bannerDismissProvider.notifier)
                      .dismiss(exposure!.percent))),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: InkWell(
                  borderRadius: BorderRadius.circular(13),
                  onTap: () => ref.read(settingsProvider.notifier)
                      .setFilter(true)
                      .catchError((_) => messenger.showSnackBar(
                          const SnackBar(content:
                              Text('설정 저장 실패 — 다시 시도해주세요')))),
                  child: Container(height: 40,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                          gradient: V1.grad,
                          borderRadius: BorderRadius.circular(13)),
                      child: const Text('필터 켜기', style: TextStyle(
                          fontSize: 12.5, fontWeight: FontWeight.w700,
                          color: Colors.white))))),
              const SizedBox(width: 8),
              Expanded(child: InkWell(
                  borderRadius: BorderRadius.circular(13),
                  onTap: () => Navigator.push(context, MaterialPageRoute(
                      builder: (_) => const DashboardScreen())),
                  child: Container(height: 40,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                          color: V1.card2,
                          border: Border.all(color: V1.stroke),
                          borderRadius: BorderRadius.circular(13)),
                      child: const Text('대시보드 확인', style: TextStyle(
                          fontSize: 12.5, fontWeight: FontWeight.w600,
                          color: V1.sub))))),
            ]),
          ]),
      ),
    ));
  }
}
