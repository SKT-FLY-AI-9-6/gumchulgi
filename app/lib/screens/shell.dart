import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/feed.dart';

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

  @override
  Widget build(BuildContext context) {
    final body = switch (_idx) {
      1 => const UploadScreen(),
      2 => const MyPageScreen(),
      _ => const FeedScreen(),
    };
    return Scaffold(
      body: body,
      bottomNavigationBar: BottomAppBar(height: 56, child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          IconButton(icon: const Icon(Icons.home_filled),
              onPressed: () {
                // 이미 홈이면 한 번 더 눌러 피드 새로고침
                if (_idx == 0) ref.read(feedProvider.notifier).refreshAll();
                setState(() => _idx = 0);
              }),
          IconButton(icon: const Icon(Icons.play_circle_outline),
              onPressed: _dummy),                       // shorts (더미)
          IconButton(icon: const Icon(Icons.add_box_outlined),
              onPressed: () => setState(() => _idx = 1)),
          IconButton(icon: const Icon(Icons.subscriptions_outlined),
              onPressed: _dummy),                       // 구독 (더미)
          IconButton(icon: const Icon(Icons.person_outline),
              onPressed: () => setState(() => _idx = 2)),
        ])),
    );
  }
}
