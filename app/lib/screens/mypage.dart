import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/auth.dart';
import '../widgets/aurora.dart';
import 'admin.dart';
import 'report.dart';
import 'dashboard.dart';

class MyPageScreen extends ConsumerWidget {
  const MyPageScreen({super.key});

  (String, Color, Color?) _badge(MyVideo v) => switch ((v.status, v.risk)) {
    ('processing', _) => ('처리 중', Aurora.sub, null),
    ('failed', _) => ('실패', Aurora.rose, null),
    (_, 'safe') => ('SAFE', Aurora.ink0, Aurora.teal),
    (_, 'corrected') => ('보정됨', Aurora.teal, null),
    (_, 'uncorrected') => ('부분 완화', Aurora.amber, null),
    _ => (v.status, Aurora.sub, null),
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider).value;
    // 관리자 계정의 내 페이지 = 운영 대시보드 (필터 ON/OFF 비교·비용 환산)
    if (user?.isAdmin == true) return const AdminScreen();
    final api = ref.read(apiProvider);
    return Scaffold(
      backgroundColor: Aurora.ink0,
      body: SafeArea(child: FutureBuilder(
        future: Future.wait([api.myVideos(), api.dashboardToday()]),
        builder: (context, snap) {
          if (snap.hasError) {
            return const Center(child: Text('불러오기 실패 — 다시 시도해주세요',
                style: TextStyle(color: Aurora.sub)));
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final vids = snap.data![0] as List<MyVideo>;
          final today = snap.data![1] as DashboardToday;
          final views = vids.fold(0, (a, v) => a + v.viewCount);
          final likes = vids.fold(0, (a, v) => a + v.likeCount);
          final pct = today.percent.clamp(0, 100) / 100;
          final mood = today.percent >= 80 ? '주의'
              : today.percent >= 50 ? '보통' : '편안함';
          return ListView(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
              children: [
            // 헤더 — 아바타를 감싼 할로 링 (오늘 노출 %)
            Row(children: [
              HaloRing(size: 84, progress: pct, stroke: 5,
                  center: Container(width: 62, height: 62,
                      decoration: const BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: LinearGradient(
                              colors: [Aurora.peri, Aurora.rose])))),
              const SizedBox(width: 16),
              Expanded(child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(user?.nickname ?? '', style: const TextStyle(
                    fontSize: 18, fontWeight: FontWeight.w800)),
                const SizedBox(height: 3),
                Text('@${user?.nickname ?? ''}', style: const TextStyle(
                    fontSize: 11.5, color: Aurora.sub)),
              ])),
              IconButton(icon: const Icon(Icons.logout,
                      color: Aurora.sub, size: 20),
                  tooltip: '로그아웃',
                  onPressed: () =>
                      ref.read(authProvider.notifier).logout()),
            ]),
            const SizedBox(height: 14),
            // 스탯
            Row(children: [
              _stat('${vids.length}', '내 릴'),
              const SizedBox(width: 8),
              _stat('$views', '조회'),
              const SizedBox(width: 8),
              _stat('$likes', '좋아요'),
            ]),
            const SizedBox(height: 12),
            // 마이 리듬 카드 → 대시보드
            InkWell(
                borderRadius: BorderRadius.circular(18),
                onTap: () => Navigator.push(context, MaterialPageRoute(
                    builder: (_) => const DashboardScreen())),
                child: InkCard(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 12),
                    child: Row(children: [
                  HaloRing(size: 44, progress: pct, stroke: 4),
                  const SizedBox(width: 12),
                  Expanded(child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    Text('오늘 ${today.percent.round()}% · $mood',
                        style: const TextStyle(fontSize: 13,
                            fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    const Text('광 노출 대시보드에서 자세히 보기',
                        style: TextStyle(fontSize: 10.5,
                            color: Aurora.sub)),
                  ])),
                  const Text('›', style: TextStyle(
                      fontSize: 15, color: Aurora.sub)),
                ]))),
            const SizedBox(height: 16),
            Text('내 릴 ${vids.length}', style: const TextStyle(
                fontSize: 13.5, fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            if (vids.isEmpty)
              const Padding(padding: EdgeInsets.only(top: 40),
                  child: Center(child: Text('업로드한 영상이 없습니다',
                      style: TextStyle(color: Aurora.sub))))
            else
              GridView.builder(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  gridDelegate:
                      const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 3, mainAxisSpacing: 8,
                          crossAxisSpacing: 8, childAspectRatio: .72),
                  itemCount: vids.length,
                  itemBuilder: (c, i) => _tile(c, api, vids[i])),
          ]);
        })),
    );
  }

  Widget _stat(String v, String l) => Expanded(child: Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: BoxDecoration(
          color: Aurora.ink1,
          border: Border.all(color: Aurora.line),
          borderRadius: BorderRadius.circular(16)),
      child: Column(children: [
        Text(v, style: const TextStyle(
            fontSize: 15, fontWeight: FontWeight.w800)),
        const SizedBox(height: 2),
        Text(l, style: const TextStyle(fontSize: 10, color: Aurora.sub)),
      ])));

  Widget _tile(BuildContext context, ApiClient api, MyVideo v) {
    final (label, fg, bg) = _badge(v);
    return InkWell(
        borderRadius: BorderRadius.circular(13),
        onTap: v.status == 'ready'
            ? () => Navigator.push(context, MaterialPageRoute(
                builder: (_) => ReportScreen(video: v)))
            : null,
        child: ClipRRect(
        borderRadius: BorderRadius.circular(13),
        child: Stack(fit: StackFit.expand, children: [
      Container(
          decoration: BoxDecoration(
              color: Aurora.ink1,
              border: Border.all(color: Aurora.line),
              borderRadius: BorderRadius.circular(13))),
      Image.network(api.absoluteUrl('/videos/${v.id}/thumb'),
          headers: api.authHeaders, fit: BoxFit.cover,
          errorBuilder: (a, b, c) => const DecoratedBox(
              decoration: BoxDecoration(gradient: LinearGradient(
                  begin: Alignment.topRight, end: Alignment.bottomLeft,
                  colors: [Color(0x338B9DF8), Color(0xFF14131C)])))),
      Positioned(left: 6, top: 6, child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
              color: bg ?? const Color(0xB30C0B13),
              border: bg == null && label != '처리 중' && label != '실패'
                  ? Border.all(color: fg.withValues(alpha: .5)) : null,
              borderRadius: BorderRadius.circular(6)),
          child: Text(label, style: TextStyle(fontSize: 8.5,
              fontWeight: FontWeight.w800, color: fg)))),
      Positioned(right: 6, bottom: 6, child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
          decoration: BoxDecoration(
              color: const Color(0xB30C0B13),
              borderRadius: BorderRadius.circular(5)),
          child: Text('${v.viewCount}', style: const TextStyle(
              fontSize: 8.5, fontWeight: FontWeight.w700)))),
    ])));
  }
}
