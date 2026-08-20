import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/banner.dart';
import '../screens/dashboard.dart';
import '../state/exposure.dart';
import '../state/settings.dart';
import '../theme.dart';

class WarningBanner extends ConsumerWidget {
  const WarningBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exposure = ref.watch(exposureProvider);
    final settings = ref.watch(settingsProvider).value;
    if (settings == null ||
        !shouldShowBanner(percent: exposure?.percent,
            filterOn: settings.filterOn)) {
      return const SizedBox.shrink();
    }
    final messenger = ScaffoldMessenger.of(context);
    return Positioned(top: 90, left: 12, right: 12, child: Material(
      color: AppColors.card, borderRadius: BorderRadius.circular(12),
      child: Padding(padding: const EdgeInsets.all(12), child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: const [
            Icon(Icons.warning_amber, color: AppColors.amber),
            SizedBox(width: 8),
            Expanded(child: Text('경고! 위험 영상에 대한 노출이 많습니다.\n'
                '필터 기능을 키는 것을 추천드립니다.',
                style: TextStyle(fontSize: 13))),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AppColors.amber,
                    foregroundColor: Colors.black),
                onPressed: () => ref.read(settingsProvider.notifier)
                    .setFilter(true).catchError((_) => messenger.showSnackBar(
                        const SnackBar(content:
                            Text('설정 저장 실패 — 다시 시도해주세요')))),
                child: const Text('필터 ON')),
            const SizedBox(width: 8),
            OutlinedButton(
                onPressed: () => Navigator.push(context, MaterialPageRoute(
                    builder: (_) => const DashboardScreen())),
                child: const Text('대시보드 확인')),
          ]),
        ]))));
  }
}
