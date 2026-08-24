import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../api/client.dart';
import '../widgets/aurora.dart';

enum _Phase { idle, uploading, processing, done, failed }

class UploadScreen extends ConsumerStatefulWidget {
  const UploadScreen({super.key});
  @override
  ConsumerState<UploadScreen> createState() => _UploadState();
}

class _UploadState extends ConsumerState<UploadScreen> {
  final _title = TextEditingController();
  XFile? _file;
  int? _fileBytes;
  double _progress = 0;
  _Phase _phase = _Phase.idle;
  int? _videoId;
  Timer? _poll;

  @override
  void dispose() {
    _title.dispose();
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _pick() async {
    final f = await ImagePicker().pickVideo(source: ImageSource.gallery);
    if (f == null || !mounted) return;
    final bytes = await f.length();
    if (!mounted) return;
    setState(() { _file = f; _fileBytes = bytes; _phase = _Phase.idle; });
  }

  Future<void> _upload() async {
    if (_file == null) return;
    setState(() { _phase = _Phase.uploading; _progress = 0; });
    try {
      final id = await ref.read(apiProvider).upload(_file!, _title.text,
          onProgress: (sent, total) {
            if (mounted) setState(() => _progress = sent / total);
          });
      if (!mounted) return;
      setState(() { _phase = _Phase.processing; _videoId = id; });
      _poll = Timer.periodic(const Duration(seconds: 3), (_) => _check());
    } catch (e) {
      if (!mounted) return;
      setState(() => _phase = _Phase.failed);
    }
  }

  Future<void> _check() async {
    try {
      final vids = await ref.read(apiProvider).myVideos();
      final v = vids.where((v) => v.id == _videoId).firstOrNull;
      if (v == null || !mounted) return;
      if (v.status == 'ready') {
        _poll?.cancel();
        setState(() => _phase = _Phase.done);
      } else if (v.status == 'failed') {
        _poll?.cancel();
        setState(() => _phase = _Phase.failed);
      }
    } catch (_) {/* 다음 폴링에서 재시도 */}
  }

  void _reset() {
    _poll?.cancel();
    setState(() {
      _file = null; _fileBytes = null; _title.clear();
      _phase = _Phase.idle; _videoId = null;
    });
  }

  String get _sizeLabel {
    final b = _fileBytes ?? 0;
    return b >= 1 << 20
        ? '${(b / (1 << 20)).toStringAsFixed(1)}MB'
        : '${(b / 1024).toStringAsFixed(0)}KB';
  }

  // ── 스테퍼 ──
  Widget _step(String label, int idx) {
    // 0 업로드, 1 안전 처리(검출·보정), 2 게시
    final current = switch (_phase) {
      _Phase.idle => -1,
      _Phase.uploading => 0,
      _Phase.processing => 1,
      _Phase.done => 3,
      _Phase.failed => -1,
    };
    final done = idx < current;
    final run = idx == current;
    return Expanded(child: Column(children: [
      Container(width: 26, height: 26, alignment: Alignment.center,
          decoration: BoxDecoration(shape: BoxShape.circle,
              gradient: run ? Aurora.grad : null,
              color: run ? null
                  : done ? Aurora.teal.withValues(alpha: .16) : Aurora.ink2,
              border: run ? null : Border.all(color: done
                  ? Aurora.teal.withValues(alpha: .5) : Aurora.line)),
          child: done
              ? const Icon(Icons.check, size: 14, color: Aurora.teal)
              : Text('${idx + 1}', style: TextStyle(fontSize: 11,
                  fontWeight: FontWeight.w800,
                  color: run ? Aurora.ink0 : Aurora.sub))),
      const SizedBox(height: 5),
      Text(label, style: const TextStyle(fontSize: 9.5, color: Aurora.sub,
          fontWeight: FontWeight.w600)),
    ]));
  }

  Widget _stepLine(bool done) => Container(
      width: 24, height: 1.5, margin: const EdgeInsets.only(bottom: 14),
      color: done ? Aurora.teal.withValues(alpha: .5) : Aurora.line);

  @override
  Widget build(BuildContext context) {
    final busy = _phase == _Phase.uploading || _phase == _Phase.processing;
    return Scaffold(
      backgroundColor: Aurora.ink0,
      appBar: AppBar(backgroundColor: Aurora.ink0,
          title: const Text('새 릴 올리기',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          actions: [if (_file != null && !busy)
            TextButton(onPressed: _reset, child: const Text('취소',
                style: TextStyle(color: Aurora.sub, fontSize: 12.5)))]),
      body: ListView(padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          children: [
        // 파일 카드 / 선택 버튼
        if (_file == null)
          InkWell(onTap: _pick, borderRadius: BorderRadius.circular(20),
              child: Container(height: 130,
                  decoration: BoxDecoration(
                      color: Aurora.ink1,
                      border: Border.all(color: Aurora.line),
                      borderRadius: BorderRadius.circular(20)),
                  child: const Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                    Icon(Icons.video_library_outlined,
                        color: Aurora.peri, size: 30),
                    SizedBox(height: 8),
                    Text('갤러리에서 영상 선택', style: TextStyle(
                        fontSize: 13.5, fontWeight: FontWeight.w700)),
                    SizedBox(height: 3),
                    Text('최대 200MB · 3분', style: TextStyle(
                        fontSize: 10.5, color: Aurora.sub)),
                  ])))
        else
          InkCard(child: Row(children: [
            Container(width: 56, height: 74,
                decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    gradient: const LinearGradient(
                        begin: Alignment.topRight,
                        end: Alignment.bottomLeft,
                        colors: [Color(0x66FB8FA5), Color(0x668B9DF8),
                            Color(0xFF1D1430)]))),
            const SizedBox(width: 12),
            Expanded(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(_file!.name, maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 14, fontWeight: FontWeight.w700)),
              const SizedBox(height: 3),
              Text(_sizeLabel, style: const TextStyle(
                  fontSize: 11, color: Aurora.sub)),
            ])),
            if (_phase == _Phase.idle)
              TextButton(onPressed: _pick, child: const Text('변경',
                  style: TextStyle(color: Aurora.peri, fontSize: 12.5))),
          ])),
        const SizedBox(height: 12),
        if (_phase == _Phase.idle) ...[
          TextField(controller: _title,
              decoration: InputDecoration(
                  labelText: '제목',
                  labelStyle: const TextStyle(
                      color: Aurora.sub, fontSize: 13.5),
                  filled: true, fillColor: Aurora.ink1,
                  enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(15),
                      borderSide: const BorderSide(color: Aurora.line)),
                  focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(15),
                      borderSide: const BorderSide(color: Aurora.peri)))),
          const SizedBox(height: 16),
          AuroraButton(label: '안전 처리 시작',
              onTap: _file == null ? null : _upload),
        ],
        // 처리 카드 (업로드 중 ~ 완료)
        if (_phase != _Phase.idle) InkCard(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(switch (_phase) {
            _Phase.uploading =>
                '업로드 중 — ${(_progress * 100).round()}%',
            _Phase.processing => '안전 처리 중',
            _Phase.done => '게시 완료',
            _ => '처리 실패',
          }, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700,
              color: _phase == _Phase.failed ? Aurora.rose : null)),
          const SizedBox(height: 14),
          Row(children: [
            _step('업로드', 0),
            _stepLine(_phase != _Phase.uploading),
            _step('검출·보정', 1),
            _stepLine(_phase == _Phase.done),
            _step('게시', 2),
          ]),
          const SizedBox(height: 12),
          if (_phase == _Phase.uploading)
            ClipRRect(borderRadius: BorderRadius.circular(3),
                child: LinearProgressIndicator(value: _progress,
                    minHeight: 6, backgroundColor: Aurora.ink2,
                    color: Aurora.peri)),
          if (_phase == _Phase.processing)
            const ClipRRect(
                child: LinearProgressIndicator(minHeight: 6,
                    backgroundColor: Color(0xFF1B1A26),
                    color: Aurora.peri)),
          const SizedBox(height: 10),
          Text(switch (_phase) {
            _Phase.uploading => '영상을 서버로 보내는 중이에요.',
            _Phase.processing =>
                '위험 구간을 검출하고 부드럽게 만드는 중이에요.\n'
                '나가도 괜찮아요 — 끝나면 피드와 내 페이지에 표시됩니다.',
            _Phase.done => '검출·보정이 끝나 피드에 게시됐어요.',
            _ => '크기(200MB)·길이(3분) 제한을 확인하고 다시 시도해주세요.',
          }, style: const TextStyle(fontSize: 11.5, color: Aurora.sub,
              height: 1.6)),
        ])),
        if (_phase == _Phase.processing || _phase == _Phase.done) ...[
          const SizedBox(height: 12),
          InkCard(padding: const EdgeInsets.symmetric(
              horizontal: 14, vertical: 4),
              child: Column(children: [
            _infoRow('판정 통과 시', '자동 게시'),
            _infoRow('원본', '함께 보관됨'),
            _infoRow('판정 기준', 'ITU-R BT.1702', last: true),
          ])),
        ],
        if (_phase == _Phase.done || _phase == _Phase.failed) ...[
          const SizedBox(height: 16),
          AuroraButton(label: '새 릴 올리기', onTap: _reset),
        ],
      ]),
    );
  }

  Widget _infoRow(String l, String r, {bool last = false}) => Container(
      padding: const EdgeInsets.symmetric(vertical: 9),
      decoration: BoxDecoration(border: last ? null : const Border(
          bottom: BorderSide(color: Color(0x0DFFFFFF)))),
      child: Row(children: [
        Expanded(child: Text(l, style: const TextStyle(
            fontSize: 12.5, color: Aurora.sub))),
        Text(r, style: const TextStyle(
            fontSize: 12.5, fontWeight: FontWeight.w600)),
      ]));
}
