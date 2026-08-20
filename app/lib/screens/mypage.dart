import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/auth.dart';
import '../theme.dart';

const _badge = {
  'processing': ('처리 중', AppColors.sub),
  'ready': ('게시됨', Colors.greenAccent),
  'failed': ('처리 실패', AppColors.red),
};

class MyPageScreen extends ConsumerWidget {
  const MyPageScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider).value;
    return Scaffold(
      appBar: AppBar(title: Text('@${user?.nickname ?? ''}'), actions: [
        IconButton(icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authProvider.notifier).logout()),
      ]),
      body: FutureBuilder(
        future: ref.read(apiProvider).myVideos(),
        builder: (context, snap) {
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final vids = snap.data as List<MyVideo>;
          if (vids.isEmpty) {
            return const Center(child: Text('업로드한 영상이 없습니다',
                style: TextStyle(color: AppColors.sub)));
          }
          return ListView.builder(itemCount: vids.length,
              itemBuilder: (_, i) {
            final v = vids[i];
            final (label, color) = _badge[v.status] ?? (v.status, AppColors.sub);
            final riskNote = v.status == 'ready' && v.risk == 'uncorrected'
                ? ' · 보정 미완(자동 스킵 대상)' : '';
            return ListTile(
              title: Text(v.title),
              subtitle: Text('조회 ${v.viewCount} · 좋아요 ${v.likeCount}$riskNote',
                  style: const TextStyle(fontSize: 12)),
              trailing: Text(label, style: TextStyle(color: color)));
          });
        }),
    );
  }
}
