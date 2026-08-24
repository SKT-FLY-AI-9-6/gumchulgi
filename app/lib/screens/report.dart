import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../widgets/brand_v1.dart';

String _mmss(double s) {
  final t = s.round();
  return '${(t ~/ 60).toString().padLeft(2, '0')}:'
      '${(t % 60).toString().padLeft(2, '0')}';
}

/// 시안 v1 — D. 내 영상 리포트 (업로더용)
class ReportScreen extends ConsumerWidget {
  final MyVideo video;
  const ReportScreen({super.key, required this.video});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(apiProvider);
    return Scaffold(
      backgroundColor: V1.bg0,
      appBar: AppBar(backgroundColor: V1.bg0,
          title: const Text('내 영상 리포트',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700))),
      body: SafeArea(top: false, child: FutureBuilder(
        future: api.videoReport(video.id),
        builder: (context, snap) {
          if (snap.hasError) {
            return const Center(child: Text('리포트를 불러오지 못했습니다',
                style: TextStyle(color: V1.sub)));
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final r = snap.data!;
          final dur = r.durationS ?? 1;
          final unresolved = r.segments.where((s) => !s.resolved).length;
          return ListView(padding: const EdgeInsets.all(20), children: [
            // 영상 카드 + 타임라인 마커
            V1Card(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                ClipRRect(borderRadius: BorderRadius.circular(14),
                    child: SizedBox(width: 86, height: 110,
                        child: Image.network(
                            api.absoluteUrl('/videos/${r.id}/thumb'),
                            headers: api.authHeaders, fit: BoxFit.cover,
                            errorBuilder: (a, b, c) => const DecoratedBox(
                                decoration: BoxDecoration(
                                    gradient: LinearGradient(
                                        colors: [Color(0xFF231038),
                                            Color(0xFF4A1230)])))))),
                const SizedBox(width: 12),
                Expanded(child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(r.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 14.5,
                          fontWeight: FontWeight.w700)),
                  const SizedBox(height: 3),
                  Text('${_mmss(dur)} · 조회 ${r.viewCount}',
                      style: const TextStyle(
                          fontSize: 11.5, color: V1.sub)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    if (r.risk == 'safe')
                      _bd('안전 판정', V1.green)
                    else ...[
                      if (r.risk == 'corrected')
                        _bd(unresolved == 0 ? '보정 완료' : '부분 완화',
                            unresolved == 0 ? V1.green : V1.amber),
                      if (r.risk == 'uncorrected')
                        _bd('보정 미완', V1.amber),
                      _bd('원본 위반 ${r.segments.length}건', V1.amber),
                    ],
                  ]),
                ])),
              ]),
              if (r.segments.isNotEmpty) ...[
                const SizedBox(height: 16),
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                  Text('00:00', style: const TextStyle(
                      fontSize: 10, color: V1.sub)),
                  Text(_mmss(dur), style: const TextStyle(
                      fontSize: 10, color: V1.sub)),
                ]),
                const SizedBox(height: 5),
                LayoutBuilder(builder: (context, box) => Stack(children: [
                  Container(height: 7, decoration: BoxDecoration(
                      color: const Color(0xFF26263A),
                      borderRadius: BorderRadius.circular(4))),
                  for (final seg in r.segments)
                    Positioned(
                        left: box.maxWidth *
                            (seg.startS / dur).clamp(0.0, 1.0),
                        width: (box.maxWidth *
                                ((seg.endS - seg.startS) / dur))
                            .clamp(3.0, box.maxWidth),
                        child: Container(height: 7,
                            decoration: BoxDecoration(
                                color: seg.resolved ? V1.amber : V1.pink,
                                borderRadius: BorderRadius.circular(4)))),
                ])),
              ],
            ])),
            // 검출된 위험 구간
            V1Card(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('검출된 위험 구간',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              if (r.segments.isEmpty)
                const Padding(padding: EdgeInsets.symmetric(vertical: 10),
                    child: Text('위반 구간이 없어요 — 안전한 영상입니다',
                        style: TextStyle(fontSize: 12, color: V1.sub)))
              else
                for (final (i, seg) in r.segments.indexed)
                  Container(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      decoration: BoxDecoration(
                          border: i == r.segments.length - 1 ? null
                              : const Border(bottom: BorderSide(
                                  color: Color(0x0FFFFFFF)))),
                      child: Row(children: [
                        Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 5),
                            decoration: BoxDecoration(
                                color: V1.card2,
                                borderRadius: BorderRadius.circular(8)),
                            child: Text(
                                '${_mmss(seg.startS)}–${_mmss(seg.endS)}',
                                style: const TextStyle(fontSize: 11,
                                    fontWeight: FontWeight.w700))),
                        const SizedBox(width: 10),
                        Expanded(child: Text(seg.rule,
                            style: const TextStyle(fontSize: 12.5,
                                fontWeight: FontWeight.w600))),
                        Text(seg.resolved ? '완화됨' : '부분 완화',
                            style: TextStyle(fontSize: 10.5,
                                fontWeight: FontWeight.w700,
                                color: seg.resolved ? V1.green : V1.amber)),
                      ])),
            ])),
            // 원본/보정본 비교 재생
            if (r.risk == 'corrected')
              Row(children: [
                Expanded(child: _abBtn(context, '원본 미리보기', false,
                    () => _play(context, api, r, 'original'))),
                const SizedBox(width: 10),
                Expanded(child: _abBtn(context, '보정본 재생', true,
                    () => _play(context, api, r, 'filtered'))),
              ]),
            // 시청자 반응
            if (r.filterOnWatchPercent != null) ...[
              const SizedBox(height: 12),
              V1Card(child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('시청자 반응', style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                Row(children: [
                  _mini('필터 ON 시청',
                      '${r.filterOnWatchPercent!.round()}%'),
                  const SizedBox(width: 8),
                  _mini('평균 시청 유지', r.avgWatchPercent == null
                      ? '—' : '${r.avgWatchPercent!.round()}%'),
                  const SizedBox(width: 8),
                  _mini('조회수', '${r.viewCount}'),
                ]),
              ])),
            ],
            const SizedBox(height: 4),
            const Center(child: Text(
                '판정 기준 ITU-R BT.1702 · 구간별 사유와 조치가 리포트에 남습니다',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 10.5, color: V1.sub,
                    height: 1.5))),
          ]);
        })),
    );
  }

  Widget _bd(String t, Color c) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
          color: c.withValues(alpha: .13),
          border: Border.all(color: c.withValues(alpha: .5)),
          borderRadius: BorderRadius.circular(9)),
      child: Text(t, style: TextStyle(fontSize: 10.5,
          fontWeight: FontWeight.w700, color: c)));

  Widget _mini(String l, String v) => Expanded(child: Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: V1.card2,
          borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l, style: const TextStyle(fontSize: 11.5, color: V1.sub)),
        const SizedBox(height: 3),
        Text(v, style: const TextStyle(fontSize: 15,
            fontWeight: FontWeight.w800, color: V1.lavender)),
      ])));

  Widget _abBtn(BuildContext context, String label, bool primary,
          VoidCallback onTap) =>
      InkWell(onTap: onTap, borderRadius: BorderRadius.circular(14),
          child: Container(height: 46, alignment: Alignment.center,
              decoration: BoxDecoration(
                  gradient: primary ? V1.grad : null,
                  color: primary ? null : V1.card,
                  border: primary ? null : Border.all(color: V1.stroke),
                  borderRadius: BorderRadius.circular(14)),
              child: Text(label, style: TextStyle(fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: primary ? Colors.white : V1.sub))));

  void _play(BuildContext context, ApiClient api, VideoReport r,
      String variant) {
    Navigator.push(context, MaterialPageRoute(builder: (_) =>
        _PreviewPlayer(
            title: variant == 'filtered' ? '보정본' : '원본',
            url: api.absoluteUrl(
                '/videos/${r.id}/stream?variant=$variant'),
            headers: api.authHeaders)));
  }
}

class _PreviewPlayer extends StatefulWidget {
  final String title, url;
  final Map<String, String> headers;
  const _PreviewPlayer({required this.title, required this.url,
      required this.headers});
  @override
  State<_PreviewPlayer> createState() => _PreviewPlayerState();
}

class _PreviewPlayerState extends State<_PreviewPlayer> {
  VideoPlayerController? _c;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _c = VideoPlayerController.networkUrl(Uri.parse(widget.url),
        httpHeaders: widget.headers)
      ..setLooping(true)
      ..initialize().then((_) {
        if (mounted) { setState(() {}); _c!.play(); }
      }).catchError((_) {
        if (mounted) setState(() => _error = true);
      });
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(backgroundColor: Colors.black,
          title: Text(widget.title)),
      body: Center(child: _error
          ? const Text('재생 실패', style: TextStyle(color: V1.sub))
          : (_c != null && _c!.value.isInitialized)
              ? AspectRatio(aspectRatio: _c!.value.aspectRatio,
                  child: VideoPlayer(_c!))
              : const CircularProgressIndicator()));
}
