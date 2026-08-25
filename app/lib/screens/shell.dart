import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/feed.dart';
import '../widgets/brand_v1.dart';
import 'feed.dart';
import 'mypage.dart';
import 'upload.dart';

class ShellScreen extends ConsumerStatefulWidget {
  const ShellScreen({super.key});
  @override
  ConsumerState<ShellScreen> createState() => _ShellState();
}

class _ShellState extends ConsumerState<ShellScreen> {
  int _idx = 0; // 0 피드, 1 업로드, 2 내페이지

  void _dummy() => ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('준비 중입니다')));

  Widget _item(IconData ic, String label, bool on, VoidCallback onTap) =>
      InkWell(onTap: onTap, borderRadius: BorderRadius.circular(12),
          child: Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: 10, vertical: 4),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Icon(ic, size: 22, color: on ? V1.violet
                    : Colors.white.withValues(alpha: .45)),
                const SizedBox(height: 3),
                Text(label, style: TextStyle(fontSize: 10.5,
                    fontWeight: FontWeight.w600,
                    color: on ? V1.violet
                        : Colors.white.withValues(alpha: .45))),
              ])));

  @override
  Widget build(BuildContext context) {
    final body = switch (_idx) {
      1 => const UploadScreen(),
      2 => const MyPageScreen(),
      _ => const FeedScreen(),
    };
    return Scaffold(
      body: body,
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
            color: const Color(0xF00A0A12),
            border: Border(top: BorderSide(
                color: Colors.white.withValues(alpha: .08)))),
        // 폰의 시스템 내비게이션 바(제스처 바)와 겹치지 않게
        // SafeArea 로 하단 인셋만큼 띄운다.
        child: SafeArea(top: false, child: SizedBox(
          height: 62,
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
          _item(Icons.home_filled, '홈', _idx == 0, () {
            // 이미 홈이면 한 번 더 눌러 피드 새로고침
            if (_idx == 0) ref.read(feedProvider.notifier).refreshAll();
            setState(() => _idx = 0);
          }),
          _item(Icons.search, '탐색', false, _dummy),
          // 가운데 그라데이션 업로드 버튼 (시안 A)
          InkWell(onTap: () => setState(() => _idx = 1),
              borderRadius: BorderRadius.circular(10),
              child: Container(width: 46, height: 32,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                      gradient: V1.grad,
                      borderRadius: BorderRadius.circular(10),
                      boxShadow: [BoxShadow(
                          color: V1.pink.withValues(alpha: .45),
                          blurRadius: 14, offset: const Offset(0, 4))]),
                  child: const Icon(Icons.add,
                      size: 22, color: Colors.white))),
          _item(Icons.notifications_none, '알림', false, _dummy),
          _item(Icons.person_outline, 'MY', _idx == 2,
              () => setState(() => _idx = 2)),
        ]))),
      ),
    );
  }
}
