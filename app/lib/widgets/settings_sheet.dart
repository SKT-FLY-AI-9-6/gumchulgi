import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/dashboard.dart';
import '../state/settings.dart';
import '../theme.dart';

void showSettingsSheet(BuildContext context) {
  showModalBottomSheet(
    context: context, backgroundColor: AppColors.card,
    builder: (_) => Consumer(builder: (context, ref, _) {
      final s = ref.watch(settingsProvider).value;
      if (s == null) return const SizedBox(height: 180);
      final n = ref.read(settingsProvider.notifier);
      return SafeArea(child: Column(mainAxisSize: MainAxisSize.min, children: [
        SwitchListTile(title: const Text('필터 기능 켜기'),
            value: s.filterOn, onChanged: n.setFilter),
        SwitchListTile(title: const Text('위험 영상 자동 스킵 켜기'),
            value: s.autoSkip, onChanged: n.setAutoSkip),
        ListTile(leading: const Icon(Icons.insights),
            title: const Text('광 노출 대시보드 확인'),
            onTap: () {
              Navigator.pop(context);
              Navigator.push(context, MaterialPageRoute(
                  builder: (_) => const DashboardScreen()));
            }),
      ]));
    }));
}
