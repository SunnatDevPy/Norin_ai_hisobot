import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';

Future<void> openNewSaleSheet(
  BuildContext context,
  WidgetRef ref, {
  int? initialClientId,
}) async {
  await ActionGuard.run('sheet:new_sale', () async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) => _NewSaleSheet(initialClientId: initialClientId),
    );
  });
}

Future<void> openSaleReviewSheet(
  BuildContext context,
  WidgetRef ref,
  Map<String, dynamic> initialSale, {
  String? suggestedClientName,
  int? duplicateSaleId,
}) async {
  await ActionGuard.run('sheet:sale_review:${asInt(initialSale['id'])}', () async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) => _SaleReviewSheet(
        initialSale: initialSale,
        suggestedClientName: suggestedClientName,
        duplicateSaleId: duplicateSaleId,
      ),
    );
  });
}

class _ManualLine {
  _ManualLine({this.productId});
  int? productId;
  final TextEditingController kgCtrl = TextEditingController();
  final TextEditingController priceCtrl = TextEditingController();

  void dispose() {
    kgCtrl.dispose();
    priceCtrl.dispose();
  }
}

class _NewSaleSheet extends ConsumerStatefulWidget {
  const _NewSaleSheet({this.initialClientId});
  final int? initialClientId;

  @override
  ConsumerState<_NewSaleSheet> createState() => _NewSaleSheetState();
}

class _NewSaleSheetState extends ConsumerState<_NewSaleSheet> with SingleTickerProviderStateMixin {
  late final TabController _tabs;
  final _picker = ImagePicker();

  // Tab 1: AI Chek
  XFile? _pickedImage;
  final _captionCtrl = TextEditingController();

  // Tab 2: Text 0-token
  final _textCtrl = TextEditingController();

  // Tab 3: Manual (supports multiple product rows!)
  int? _manualClientId;
  final List<_ManualLine> _manualLines = [_ManualLine()];
  final _manualNoteCtrl = TextEditingController();
  bool _confirmNow = true;
  bool _postToGroup = true;

  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 3, vsync: this);
    _manualClientId = widget.initialClientId;
  }

  @override
  void dispose() {
    _tabs.dispose();
    _captionCtrl.dispose();
    _textCtrl.dispose();
    for (final line in _manualLines) {
      line.dispose();
    }
    _manualNoteCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickPhoto(ImageSource source) async {
    try {
      final file = await _picker.pickImage(source: source, imageQuality: 88, maxWidth: 2000);
      if (file != null && mounted) {
        setState(() => _pickedImage = file);
      }
    } catch (e) {
      if (mounted) showSnack(context, "Rasm olishda xato: $e", error: true);
    }
  }

  Future<void> _submitImage() async {
    if (_pickedImage == null) {
      showSnack(context, "Avval chek rasmini tanlang", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).uploadFile(
              '/sales/from-image',
              _pickedImage!.path,
              caption: _captionCtrl.text,
            ),
      );
      if (res['error'] != null && res['sale'] == null) {
        if (mounted) showSnack(context, asStr(res['error']), error: true);
        return;
      }
      final sale = asMap(res['sale']);
      invalidateOperationalData(ref);
      if (!mounted) return;
      Navigator.pop(context);
      await openSaleReviewSheet(
        context,
        ref,
        sale,
        suggestedClientName: res['suggested_client_name']?.toString(),
        duplicateSaleId: res['duplicate_sale_id'] == null ? null : asInt(res['duplicate_sale_id']),
      );
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitText() async {
    final text = _textCtrl.text.trim();
    if (text.isEmpty) {
      showSnack(context, "Buyruq matnini kiriting", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post('/sales/from-text', data: {'text': text}),
      );
      final sale = res['sale'] == null ? <String, dynamic>{} : asMap(res['sale']);
      if (sale.isEmpty) {
        if (mounted) {
          showSnack(
            context,
            "Sotuv ajratilmadi. Namuna: \"Anvar 15 kg\" yoki \"Sardor 10 dona\"",
            error: true,
          );
        }
        return;
      }
      invalidateOperationalData(ref);
      if (!mounted) return;
      Navigator.pop(context);
      await openSaleReviewSheet(
        context,
        ref,
        sale,
        duplicateSaleId: res['duplicate_sale_id'] == null ? null : asInt(res['duplicate_sale_id']),
      );
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitManual(List<Map<String, dynamic>> products) async {
    final defaultPid = products.isNotEmpty ? asInt(products.first['id']) : 0;
    final itemsPayload = <Map<String, dynamic>>[];
    for (final line in _manualLines) {
      final pid = line.productId ?? defaultPid;
      final kg = parseNumberInput(line.kgCtrl.text);
      final priceOverride = parseNumberInput(line.priceCtrl.text);
      if (pid <= 0 || kg == null || kg <= 0) {
        showSnack(context, "Har bir qatorda mahsulot va vaznni to'g'ri kiriting", error: true);
        return;
      }
      itemsPayload.add({
        'product_id': pid,
        'weight_kg': kg,
        if (priceOverride != null && priceOverride > 0) 'unit_sell_price': priceOverride,
      });
    }
    if (itemsPayload.isEmpty) {
      showSnack(context, "Kamida 1 ta mahsulot kiriting", error: true);
      return;
    }
    if (_confirmNow && _manualClientId == null) {
      showSnack(context, "Darhol tasdiqlash uchun mijozni tanlang", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post(
          '/sales',
          data: {
            'client_id': _manualClientId,
            'items': itemsPayload,
            'note': _manualNoteCtrl.text.trim(),
            'confirm_now': _confirmNow,
            'post_to_group': _confirmNow && _postToGroup,
          },
        ),
      );
      invalidateOperationalData(ref);
      if (!mounted) return;
      final sale = asMap(res['sale']);
      Navigator.pop(context);
      if (_confirmNow) {
        final grpOk = res['group_posted'] == true;
        showSnack(
          context,
          grpOk ? "Sotuv saqlandi va Telegram guruhga yuborildi" : "Sotuv tasdiqlandi",
        );
      } else {
        await openSaleReviewSheet(
          context,
          ref,
          sale,
          duplicateSaleId:
              res['duplicate_sale_id'] == null ? null : asInt(res['duplicate_sale_id']),
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  (double, double) _computeManualPreview(List<Map<String, dynamic>> products) {
    double totalKg = 0;
    double totalSum = 0;
    for (final line in _manualLines) {
      final pid = line.productId ?? (products.isNotEmpty ? asInt(products.first['id']) : 0);
      final kg = parseNumberInput(line.kgCtrl.text) ?? 0;
      double price = parseNumberInput(line.priceCtrl.text) ?? 0;
      if (price <= 0) {
        for (final p in products) {
          if (asInt(p['id']) == pid) {
            price = asDouble(p['default_sell_price']);
            break;
          }
        }
      }
      if (kg > 0) {
        totalKg += kg;
        totalSum += kg * price;
      }
    }
    return (totalKg, totalSum);
  }

  @override
  Widget build(BuildContext context) {
    final clientsAsync = ref.watch(clientsProvider);
    final productsAsync = ref.watch(productsProvider);
    final clients = clientsAsync.valueOrNull ?? const <Map<String, dynamic>>[];
    final products = productsAsync.valueOrNull ?? const <Map<String, dynamic>>[];
    if (products.isNotEmpty) {
      for (final line in _manualLines) {
        line.productId ??= asInt(products.first['id']);
      }
    }
    final (previewKg, previewSum) = _computeManualPreview(products);

    return Padding(
      padding: EdgeInsets.only(
        bottom: math.max(
          MediaQuery.viewInsetsOf(context).bottom,
          MediaQuery.viewPaddingOf(context).bottom,
        ),
      ),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.78,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Row(
                children: [
                  const Text(
                    "Yangi Sotuv",
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                  ),
                  const Spacer(),
                  IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close)),
                ],
              ),
            ),
            TabBar(
              controller: _tabs,
              tabs: const [
                Tab(icon: Icon(Icons.document_scanner_outlined), text: "AI Chek"),
                Tab(icon: Icon(Icons.bolt_rounded), text: "Tezkor Matn"),
                Tab(icon: Icon(Icons.edit_note_rounded), text: "Qo'lda"),
              ],
            ),
            Expanded(
              child: TabBarView(
                controller: _tabs,
                children: [
                  // 1. AI Chek
                  ListView(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 36),
                    children: [
                      if (_pickedImage != null)
                        ClipRRect(
                          borderRadius: BorderRadius.circular(16),
                          child: Image.file(
                            File(_pickedImage!.path),
                            height: 210,
                            fit: BoxFit.cover,
                          ),
                        )
                      else
                        Container(
                          height: 150,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(
                              color: NorinPalette.emerald.withValues(alpha: 0.4),
                            ),
                            color: NorinPalette.emerald.withValues(alpha: 0.06),
                          ),
                          child: const Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.camera_alt_outlined, size: 38, color: NorinPalette.emerald),
                              SizedBox(height: 8),
                              Text(
                                "Chek yoki nakladnoy rasmini tanlang",
                                style: TextStyle(fontWeight: FontWeight.w600),
                              ),
                            ],
                          ),
                        ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: _busy ? null : () => _pickPhoto(ImageSource.camera),
                              icon: const Icon(Icons.camera_alt_outlined),
                              label: const Text("Kamera"),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: _busy ? null : () => _pickPhoto(ImageSource.gallery),
                              icon: const Icon(Icons.photo_library_outlined),
                              label: const Text("Galereya"),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: _captionCtrl,
                        decoration: const InputDecoration(
                          labelText: "Mijoz nomi / izoh (ixtiyoriy)",
                          hintText: "Masalan: Anvar",
                          prefixIcon: Icon(Icons.person_outline),
                        ),
                      ),
                      const SizedBox(height: 18),
                      FilledButton.icon(
                        onPressed: _busy ? null : _submitImage,
                        icon: _busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.auto_awesome_rounded),
                        label: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          child: Text(_busy ? "AI tahlil qilmoqda..." : "AI bilan o'qish"),
                        ),
                      ),
                    ],
                  ),
                  // 2. Tezkor Matn (0 token)
                  ListView(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 36),
                    children: [
                      Card(
                        color: NorinPalette.emerald.withValues(alpha: 0.08),
                        child: const Padding(
                          padding: EdgeInsets.all(14),
                          child: Row(
                            children: [
                              Icon(Icons.bolt_rounded, color: NorinPalette.emerald),
                              SizedBox(width: 10),
                              Expanded(
                                child: Text(
                                  "Ovozda aytib yoki matnda yozib tezkor kiriting",
                                  style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: _textCtrl,
                        minLines: 2,
                        maxLines: 4,
                        decoration: const InputDecoration(
                          labelText: "Buyruq matni",
                          hintText: "Masalan: Anvar 15 kg yoki Sardor 10 dona",
                        ),
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        children: [
                          for (final sample in const [
                            "Anvar 10 kg",
                            "Sardor 15 dona",
                          ])
                            ActionChip(
                              label: Text(sample),
                              onPressed: () => _textCtrl.text = sample,
                            ),
                        ],
                      ),
                      const SizedBox(height: 18),
                      FilledButton.icon(
                        onPressed: _busy ? null : _submitText,
                        icon: const Icon(Icons.check_rounded),
                        label: const Padding(
                          padding: EdgeInsets.symmetric(vertical: 14),
                          child: Text("Matndan yaratish"),
                        ),
                      ),
                    ],
                  ),
                  // 3. Qo'lda (ko'p mahsulot qatorli)
                  ListView(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 36),
                    children: [
                      DropdownButtonFormField<int>(
                        key: ValueKey('cli_$_manualClientId'),
                        initialValue: _manualClientId,
                        decoration: const InputDecoration(
                          labelText: "Mijoz",
                          prefixIcon: Icon(Icons.person_outline),
                        ),
                        items: clients
                            .map(
                              (c) => DropdownMenuItem<int>(
                                value: asInt(c['id']),
                                child: Text(asStr(c['name'])),
                              ),
                            )
                            .toList(),
                        onChanged: (v) => setState(() => _manualClientId = v),
                      ),
                      const SizedBox(height: 12),
                      for (int i = 0; i < _manualLines.length; i++) ...[
                        Card(
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              children: [
                                Row(
                                  children: [
                                    Expanded(
                                      child: DropdownButtonFormField<int>(
                                        key: ValueKey('prod_${i}_${_manualLines[i].productId}'),
                                        initialValue: _manualLines[i].productId,
                                        decoration: const InputDecoration(
                                          labelText: "Mahsulot",
                                          prefixIcon: Icon(Icons.inventory_2_outlined),
                                        ),
                                        items: products
                                            .map(
                                              (p) => DropdownMenuItem<int>(
                                                value: asInt(p['id']),
                                                child: Text(
                                                  "${asStr(p['name'])} (${formatCompactUzs(asDouble(p['default_sell_price']))}/${asStr(p['unit'], 'kg')})",
                                                ),
                                              ),
                                            )
                                            .toList(),
                                        onChanged: (v) => setState(() => _manualLines[i].productId = v),
                                      ),
                                    ),
                                    if (_manualLines.length > 1) ...[
                                      const SizedBox(width: 6),
                                      IconButton(
                                        icon: const Icon(Icons.delete_outline, color: NorinPalette.danger),
                                        onPressed: () {
                                          setState(() {
                                            final removed = _manualLines.removeAt(i);
                                            removed.dispose();
                                          });
                                        },
                                      ),
                                    ],
                                  ],
                                ),
                                const SizedBox(height: 10),
                                Row(
                                  children: [
                                    Expanded(
                                      child: TextField(
                                        controller: _manualLines[i].kgCtrl,
                                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                        onChanged: (_) => setState(() {}),
                                        decoration: const InputDecoration(
                                          labelText: "Miqdor (kg/dona)",
                                          hintText: "10.5",
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: TextField(
                                        controller: _manualLines[i].priceCtrl,
                                        keyboardType: TextInputType.number,
                                        onChanged: (_) => setState(() {}),
                                        decoration: const InputDecoration(
                                          labelText: "Narx (ixtiyoriy)",
                                          hintText: "Avto",
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 8),
                      ],
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton.icon(
                          onPressed: _busy
                              ? null
                              : () {
                                  setState(() {
                                    _manualLines.add(
                                      _ManualLine(
                                        productId: products.isNotEmpty ? asInt(products.first['id']) : null,
                                      ),
                                    );
                                  });
                                },
                          icon: const Icon(Icons.add_circle_outline_rounded),
                          label: const Text("+ Mahsulot qatori qo'shish"),
                        ),
                      ),
                      if (previewKg > 0) ...[
                        const SizedBox(height: 6),
                        Card(
                          color: NorinPalette.emerald.withValues(alpha: 0.12),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                            child: Row(
                              children: [
                                Text(
                                  "Jami: ${formatKg(previewKg)}",
                                  style: tNumStyle.copyWith(fontWeight: FontWeight.w700),
                                ),
                                const Spacer(),
                                Text(
                                  "~ ${formatUzs(previewSum)}",
                                  style: tNumStyle.copyWith(
                                    fontWeight: FontWeight.w900,
                                    color: NorinPalette.emeraldLight,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                      const SizedBox(height: 10),
                      TextField(
                        controller: _manualNoteCtrl,
                        decoration: const InputDecoration(labelText: "Izoh (ixtiyoriy)"),
                      ),
                      const SizedBox(height: 10),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text("Darhol tasdiqlash", style: TextStyle(fontWeight: FontWeight.w600)),
                        value: _confirmNow,
                        onChanged: (v) => setState(() => _confirmNow = v),
                      ),
                      if (_confirmNow)
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text("Telegram guruhga yuborish"),
                          value: _postToGroup,
                          onChanged: (v) => setState(() => _postToGroup = v),
                        ),
                      const SizedBox(height: 14),
                      FilledButton.icon(
                        onPressed: _busy ? null : () => _submitManual(products),
                        icon: const Icon(Icons.save_rounded),
                        label: const Padding(
                          padding: EdgeInsets.symmetric(vertical: 14),
                          child: Text("Saqlash"),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SaleReviewSheet extends ConsumerStatefulWidget {
  const _SaleReviewSheet({
    required this.initialSale,
    this.suggestedClientName,
    this.duplicateSaleId,
  });

  final Map<String, dynamic> initialSale;
  final String? suggestedClientName;
  final int? duplicateSaleId;

  @override
  ConsumerState<_SaleReviewSheet> createState() => _SaleReviewSheetState();
}

class _SaleReviewSheetState extends ConsumerState<_SaleReviewSheet> {
  late Map<String, dynamic> _sale;
  bool _postToGroup = true;
  bool _busy = false;
  late String? _suggested;

  @override
  void initState() {
    super.initState();
    _sale = widget.initialSale;
    _suggested = widget.suggestedClientName;
  }

  Future<void> _changeClient(int clientId) async {
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).patch(
          '/sales/${asInt(_sale['id'])}/client',
          data: {'client_id': clientId},
        ),
      );
      setState(() {
        _sale = asMap(res['sale']);
        _suggested = null;
      });
      invalidateOperationalData(ref);
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _quickCreateSuggestedClient(String name) async {
    setState(() => _busy = true);
    try {
      final cli = asMap(
        await ref.read(apiClientProvider).post('/clients', data: {'name': name.trim()}),
      );
      ref.invalidate(clientsProvider);
      await _changeClient(asInt(cli['id']));
      if (mounted) showSnack(context, "Mijoz \"$name\" yaratildi va tanlandi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editItemDialog(Map<String, dynamic> item) async {
    final products = ref.read(productsProvider).valueOrNull ?? const <Map<String, dynamic>>[];
    int selectedProdId = asInt(item['product_id']);
    final kgCtrl = TextEditingController(text: asDouble(item['weight_kg']).toString());
    final priceCtrl = TextEditingController(text: asDouble(item['unit_sell_price']).round().toString());

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text("Qatorni tahrirlash (${asStr(item['product_name'])})"),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (products.isNotEmpty)
                DropdownButtonFormField<int>(
                  key: ValueKey('edit_prod_$selectedProdId'),
                  initialValue: selectedProdId,
                  decoration: const InputDecoration(labelText: "Mahsulot"),
                  items: products
                      .map(
                        (p) => DropdownMenuItem<int>(
                          value: asInt(p['id']),
                          child: Text(asStr(p['name'])),
                        ),
                      )
                      .toList(),
                  onChanged: (v) => setDlg(() => selectedProdId = v ?? selectedProdId),
                ),
              const SizedBox(height: 10),
              TextField(
                controller: kgCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: "Vazn / Miqdor"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: priceCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Narx (so'm)"),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Saqlash")),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final kg = parseNumberInput(kgCtrl.text);
    final price = parseNumberInput(priceCtrl.text);
    if (kg == null || kg <= 0 || price == null || price <= 0) {
      if (mounted) showSnack(context, "Vazn va narx musbat bo'lishi kerak", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).patch(
          '/sales/items/${asInt(item['id'])}',
          data: {'product_id': selectedProdId, 'weight_kg': kg, 'unit_sell_price': price},
        ),
      );
      setState(() => _sale = asMap(res['sale']));
      invalidateOperationalData(ref);
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmSale() async {
    if (_sale['client_id'] == null) {
      showSnack(context, "Tasdiqlashdan oldin mijozni tanlang", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post(
          '/sales/${asInt(_sale['id'])}/confirm',
          data: {'post_to_group': _postToGroup},
        ),
      );
      invalidateOperationalData(ref);
      if (!mounted) return;
      Navigator.pop(context);
      final grpOk = res['group_posted'] == true;
      showSnack(
        context,
        grpOk ? "Tasdiqlandi va guruhga yuborildi" : "Sotuv tasdiqlandi",
      );
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _postGroup() async {
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post('/sales/${asInt(_sale['id'])}/post-group'),
      );
      invalidateOperationalData(ref);
      if (mounted) {
        showSnack(
          context,
          asStr(res['message'], res['posted'] == true ? "Guruhga yuborildi" : "Yuborilmadi"),
          error: res['posted'] != true,
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _unpostGroup() async {
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post('/sales/${asInt(_sale['id'])}/unpost-group'),
      );
      setState(() => _sale = asMap(res['sale']));
      invalidateOperationalData(ref);
      if (mounted) showSnack(context, "Guruh xabari o'chirildi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _quickPayForSale(int clientId) async {
    final amountCtrl = TextEditingController(text: asDouble(_sale['total_amount']).round().toString());
    final noteCtrl = TextEditingController(text: "Sotuv #${asInt(_sale['id'])}");
    String method = 'cash';
    bool postGroup = _sale['group_chat_id'] != null;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text("Pul olish (${asStr(_sale['client_name'], 'Mijoz')})"),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: amountCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: "Summa (so'm) *"),
                ),
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: 'cash', label: Text("Naqd")),
                    ButtonSegment(value: 'card', label: Text("Karta")),
                    ButtonSegment(value: 'transfer', label: Text("O'tkazma")),
                  ],
                  selected: {method},
                  onSelectionChanged: (s) => setDlg(() => method = s.first),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: noteCtrl,
                  decoration: const InputDecoration(labelText: "Izoh (ixtiyoriy)"),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text("Telegram guruhga yuborish"),
                  value: postGroup,
                  onChanged: (v) => setDlg(() => postGroup = v),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Saqlash")),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final amount = parseNumberInput(amountCtrl.text);
    if (amount == null || amount <= 0) {
      if (mounted) showSnack(context, "Summa 0 dan katta bo'lishi kerak", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post(
          '/payments',
          data: {
            'client_id': clientId,
            'amount': amount,
            'payment_method': method,
            'note': noteCtrl.text.trim(),
            'post_to_group': postGroup,
          },
        ),
      );
      invalidateOperationalData(ref);
      if (mounted) {
        showSnack(
          context,
          res['group_posted'] == true
              ? "To'lov qabul qilindi va guruhga yuborildi"
              : "To'lov qayd etildi",
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _shareReceipt() async {
    final items = asMapList(_sale['items']);
    final buf = StringBuffer()
      ..writeln("🧾 Sotuv AI — Chek #${asInt(_sale['id'])}")
      ..writeln("Mijoz: ${asStr(_sale['client_name'], 'Tanlanmagan')}")
      ..writeln("Sana: ${formatLocalDateTime(asStr(_sale['created_at']))}")
      ..writeln("");
    for (final it in items) {
      buf.writeln(
        "• ${asStr(it['product_name'])}: ${formatKg(asDouble(it['weight_kg']), unit: asStr(it['unit'], 'kg'))} × ${formatUzs(asDouble(it['unit_sell_price']))} = ${formatUzs(asDouble(it['line_total']))}",
      );
    }
    buf
      ..writeln("")
      ..writeln("Jami vazn: ${formatKg(asDouble(_sale['total_weight_kg']))}")
      ..writeln("Jami summa: ${formatUzs(asDouble(_sale['total_amount']))}");
    await Share.share(buf.toString().trim());
  }

  Future<void> _deleteSale() async {
    final yes = await showConfirmDialog(
      context,
      title: "Sotuvni o'chirish",
      message: "Sotuv #${asInt(_sale['id'])} o'chirilsinmi?",
      confirmLabel: "O'chirish",
      destructive: true,
    );
    if (!yes) return;
    setState(() => _busy = true);
    try {
      await ref.read(apiClientProvider).delete('/sales/${asInt(_sale['id'])}');
      invalidateOperationalData(ref);
      if (mounted) {
        Navigator.pop(context);
        showSnack(context, "Sotuv o'chirildi");
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final clients = ref.watch(clientsProvider).valueOrNull ?? const <Map<String, dynamic>>[];
    final items = asMapList(_sale['items']);
    final status = asStr(_sale['status'], 'pending');
    final clientId = _sale['client_id'] == null ? null : asInt(_sale['client_id']);
    final isConfirmed = status == 'confirmed';
    final hasGroupMsg = _sale['group_message_id'] != null;

    return Padding(
      padding: EdgeInsets.only(
        bottom: math.max(
          MediaQuery.viewInsetsOf(context).bottom,
          MediaQuery.viewPaddingOf(context).bottom,
        ),
      ),
      child: DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.78,
        minChildSize: 0.5,
        maxChildSize: 0.94,
        builder: (ctx, sc) => ListView(
          controller: sc,
          padding: EdgeInsets.fromLTRB(20, 4, 20, screenBottomClearance(ctx, extra: 40)),
          children: [
            Row(
              children: [
                Text(
                  "Sotuv #${asInt(_sale['id'])}",
                  style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                ),
                const SizedBox(width: 10),
                StatusBadge(
                  label: isConfirmed ? "Tasdiqlangan" : "Kutilmoqda",
                  color: isConfirmed ? NorinPalette.profit : NorinPalette.amber,
                ),
                const Spacer(),
                IconButton(
                  tooltip: "Chekni ulashish",
                  icon: const Icon(Icons.share_rounded),
                  onPressed: _busy ? null : _shareReceipt,
                ),
                IconButton(
                  tooltip: "O'chirish",
                  icon: const Icon(Icons.delete_outline, color: NorinPalette.danger),
                  onPressed: _busy ? null : _deleteSale,
                ),
              ],
            ),
            if (widget.duplicateSaleId != null) ...[
              const SizedBox(height: 10),
              Card(
                color: NorinPalette.amber.withValues(alpha: 0.14),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(
                    children: [
                      const Icon(Icons.warning_amber_rounded, color: NorinPalette.amber),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          "Bugun shunga o'xshash Sotuv #${widget.duplicateSaleId} kiritilgan",
                          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 12),
            DropdownButtonFormField<int>(
              key: ValueKey('review_cli_$clientId'),
              initialValue: clientId,
              decoration: const InputDecoration(
                labelText: "Mijoz",
                prefixIcon: Icon(Icons.person_outline),
              ),
              items: clients
                  .map(
                    (c) => DropdownMenuItem<int>(
                      value: asInt(c['id']),
                      child: Text(asStr(c['name'])),
                    ),
                  )
                  .toList(),
              onChanged: _busy ? null : (v) => v != null ? _changeClient(v) : null,
            ),
            if (_suggested != null && _suggested!.trim().isNotEmpty && clientId == null) ...[
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: _busy ? null : () => _quickCreateSuggestedClient(_suggested!),
                icon: const Icon(Icons.person_add_alt_1_rounded),
                label: Text("+ \"${_suggested!}\" mijoz yaratish"),
              ),
            ],
            const SizedBox(height: 14),
            const Text(
              "Mahsulotlar (tahrirlash uchun bosing)",
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            Card(
              child: Column(
                children: [
                  for (int i = 0; i < items.length; i++) ...[
                    if (i > 0) const Divider(),
                    ListTile(
                      onTap: _busy ? null : () => _editItemDialog(items[i]),
                      title: Text(
                        asStr(items[i]['product_name']),
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      subtitle: Text(
                        "${formatKg(asDouble(items[i]['weight_kg']), unit: asStr(items[i]['unit'], 'kg'))} × ${formatUzs(asDouble(items[i]['unit_sell_price']))}",
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            formatUzs(asDouble(items[i]['line_total'])),
                            style: tNumStyle.copyWith(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(width: 6),
                          const Icon(Icons.edit_outlined, size: 18),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 14),
            Card(
              color: NorinPalette.emerald.withValues(alpha: 0.08),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  children: [
                    Row(
                      children: [
                        const Text("Jami vazn:", style: TextStyle(fontWeight: FontWeight.w600)),
                        const Spacer(),
                        Text(
                          formatKg(asDouble(_sale['total_weight_kg'])),
                          style: tNumStyle.copyWith(fontWeight: FontWeight.w800),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        const Text("Jami summa:", style: TextStyle(fontWeight: FontWeight.w700)),
                        const Spacer(),
                        Text(
                          formatUzs(asDouble(_sale['total_amount'])),
                          style: tNumStyle.copyWith(
                            fontWeight: FontWeight.w900,
                            fontSize: 17,
                            color: NorinPalette.emerald,
                          ),
                        ),
                      ],
                    ),
                    if (_sale['total_profit'] != null) ...[
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          const Text("Foyda:", style: TextStyle(fontSize: 12.5)),
                          const Spacer(),
                          Text(
                            formatUzs(asDouble(_sale['total_profit'])),
                            style: tNumStyle.copyWith(
                              fontWeight: FontWeight.w700,
                              color: NorinPalette.profit,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
            if (!isConfirmed) ...[
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text("Telegram guruhga yuborish"),
                value: _postToGroup,
                onChanged: (v) => setState(() => _postToGroup = v),
              ),
              const SizedBox(height: 10),
              FilledButton.icon(
                onPressed: _busy ? null : _confirmSale,
                icon: const Icon(Icons.check_circle_outline_rounded),
                label: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 14),
                  child: Text("Tasdiqlash", style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ),
            ] else ...[
              if (clientId != null) ...[
                FilledButton.icon(
                  onPressed: _busy ? null : () => _quickPayForSale(clientId),
                  icon: const Icon(Icons.payments_outlined),
                  label: const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: Text("Pulini oldim", style: TextStyle(fontWeight: FontWeight.w700)),
                  ),
                ),
                const SizedBox(height: 10),
              ],
              Row(
                children: [
                  Expanded(
                    child: FilledButton.tonalIcon(
                      onPressed: _busy ? null : _postGroup,
                      icon: const Icon(Icons.send_rounded),
                      label: Text(hasGroupMsg ? "Qayta yuborish" : "Guruhga yuborish"),
                    ),
                  ),
                  if (hasGroupMsg) ...[
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _busy ? null : _unpostGroup,
                        icon: const Icon(Icons.unpublished_outlined),
                        label: const Text("Guruhdan o'chirish"),
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
