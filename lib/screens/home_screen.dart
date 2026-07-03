import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../models/expense.dart';
import '../services/storage_service.dart';
import '../services/ocr_service.dart';

class HomeScreen extends StatefulWidget {
  final List<Expense> initialExpenses;
  final BaiduOcrService ocrService;

  const HomeScreen({
    super.key,
    required this.initialExpenses,
    required this.ocrService,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentTab = 0;
  late List<Expense> _expenses;
  final StorageService _storage = StorageService();
  final ImagePicker _imagePicker = ImagePicker();

  // 记账表单
  final _amountController = TextEditingController();
  final _noteController = TextEditingController();
  String _selectedCategory = ExpenseCategory.expenseCategories.first.name;
  DateTime _selectedDate = DateTime.now();
  bool _isExpense = true;
  bool _isOcrProcessing = false; // OCR 识别中

  // 筛选
  String? _filterCategory;
  DateTime? _filterMonth;
  bool? _filterType;

  // 统计
  DateTime _statsMonth = DateTime.now();

  @override
  void initState() {
    super.initState();
    _expenses = List.from(widget.initialExpenses);
  }

  @override
  void dispose() {
    _amountController.dispose();
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    await _storage.saveExpenses(_expenses);
  }

  void _addExpense() {
    final amountText = _amountController.text.trim();
    if (amountText.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入金额')),
      );
      return;
    }
    final amount = double.tryParse(amountText);
    if (amount == null || amount <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入有效的金额')),
      );
      return;
    }

    setState(() {
      _expenses.insert(
        0,
        Expense(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          amount: amount,
          categoryName: _selectedCategory,
          date: _selectedDate,
          note: _noteController.text.trim().isEmpty
              ? null
              : _noteController.text.trim(),
          isExpense: _isExpense,
        ),
      );
    });

    _amountController.clear();
    _noteController.clear();
    setState(() {
      _selectedCategory = _isExpense
          ? ExpenseCategory.expenseCategories.first.name
          : ExpenseCategory.incomeCategories.first.name;
      _selectedDate = DateTime.now();
    });

    _save();

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(_isExpense ? '支出记录成功！' : '收入记录成功！'),
        duration: const Duration(seconds: 1),
      ),
    );
  }

  void _deleteExpense(int index) {
    _confirmDelete(index); // 复用同一个确认弹窗
  }

  Future<bool> _confirmDelete(int index) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('确认删除'),
        content: const Text('确定要删除这笔记录吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () {
              setState(() => _expenses.removeAt(index));
              _save();
              Navigator.pop(ctx, true);
            },
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    return confirmed ?? false;
  }

  // ==================== 识图功能 ====================

  /// 弹出选择：拍照 or 相册
  void _startOcr() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.camera_alt, color: Colors.orange),
              title: const Text('拍照'),
              subtitle: const Text('用相机拍摄支付截图或小票'),
              onTap: () {
                Navigator.pop(ctx);
                _pickAndRecognize(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library, color: Colors.blue),
              title: const Text('从相册选择'),
              subtitle: const Text('选择已有的截图或照片'),
              onTap: () {
                Navigator.pop(ctx);
                _pickAndRecognize(ImageSource.gallery);
              },
            ),
          ],
        ),
      ),
    );
  }

  /// 选取图片并调用 OCR 识别
  Future<void> _pickAndRecognize(ImageSource source) async {
    try {
      // 选取图片
      final picked = await _imagePicker.pickImage(
        source: source,
        imageQuality: 90, // 压缩到 90% 质量，减小上传体积
      );

      if (picked == null) return; // 用户取消

      // 显示加载中
      setState(() => _isOcrProcessing = true);

      // 调用百度 OCR
      final result = await widget.ocrService.recognizeImage(File(picked.path));

      setState(() => _isOcrProcessing = false);

      // 显示识别结果，让用户确认
      if (mounted) {
        _showOcrResultDialog(result);
      }
    } catch (e) {
      setState(() => _isOcrProcessing = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('识图失败: ${e.toString().replaceAll('Exception: ', '')}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  /// 显示识别结果对话框
  void _showOcrResultDialog(OcrResult result) {
    final hasAmount = result.amount != null;
    final hasPayee = result.payee != null;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.auto_awesome, color: Colors.orange, size: 22),
            SizedBox(width: 6),
            Text('识别结果'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (hasAmount)
              Row(
                children: [
                  const Text('💲 金额：', style: TextStyle(fontSize: 15)),
                  Text(
                    '¥${result.amount!.toStringAsFixed(2)}',
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                      color: Colors.red,
                    ),
                  ),
                ],
              ),
            if (hasAmount) const SizedBox(height: 10),
            if (hasPayee)
              Row(
                children: [
                  const Text('🏪 收款方：', style: TextStyle(fontSize: 15)),
                  Flexible(
                    child: Text(
                      result.payee!,
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.bold),
                    ),
                  ),
                ],
              ),
            if (hasPayee) const SizedBox(height: 10),
            if (!hasAmount && !hasPayee)
              const Text('未能提取到金额或收款方'),
            if (result.rawText.isNotEmpty) ...[
              const Divider(height: 20),
              Text(
                '原始识别文字：',
                style: TextStyle(fontSize: 12, color: Colors.grey[500]),
              ),
              const SizedBox(height: 6),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  result.rawText,
                  style: const TextStyle(fontSize: 12, height: 1.4),
                  maxLines: 8,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('取消'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              // 自动填入表单
              if (hasAmount) {
                _amountController.text = result.amount!.toStringAsFixed(2);
              }
              if (hasPayee) {
                _noteController.text = '收款方: ${result.payee}';
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.orange),
            child: const Text('填入表单'),
          ),
        ],
      ),
    );
  }

  // ==================== 筛选相关 ====================

  List<Expense> get _filteredExpenses {
    var list = List<Expense>.from(_expenses);
    if (_filterCategory != null) {
      list = list.where((e) => e.categoryName == _filterCategory).toList();
    }
    if (_filterMonth != null) {
      list = list
          .where((e) =>
              e.date.year == _filterMonth!.year &&
              e.date.month == _filterMonth!.month)
          .toList();
    }
    if (_filterType != null) {
      list = list.where((e) => e.isExpense == _filterType).toList();
    }
    return list;
  }

  Map<String, Map<String, double>> _getMonthStats(DateTime month) {
    final expenseMap = <String, double>{};
    final incomeMap = <String, double>{};
    for (final cat in ExpenseCategory.expenseCategories) {
      expenseMap[cat.name] = 0;
    }
    for (final cat in ExpenseCategory.incomeCategories) {
      incomeMap[cat.name] = 0;
    }
    for (final e in _expenses) {
      if (e.date.year == month.year && e.date.month == month.month) {
        if (e.isExpense) {
          expenseMap[e.categoryName] =
              (expenseMap[e.categoryName] ?? 0) + e.amount;
        } else {
          incomeMap[e.categoryName] =
              (incomeMap[e.categoryName] ?? 0) + e.amount;
        }
      }
    }
    return {'expense': expenseMap, 'income': incomeMap};
  }

  List<ExpenseCategory> get _currentCategories => _isExpense
      ? ExpenseCategory.expenseCategories
      : ExpenseCategory.incomeCategories;

  void _toggleType(bool isExpense) {
    setState(() {
      _isExpense = isExpense;
      _selectedCategory = isExpense
          ? ExpenseCategory.expenseCategories.first.name
          : ExpenseCategory.incomeCategories.first.name;
    });
  }

  // ==================== 主页面 ====================

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentTab,
        children: [
          _buildBillList(),
          _buildAddExpense(),
          _buildStats(),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentTab,
        onTap: (i) => setState(() => _currentTab = i),
        selectedItemColor: Colors.orange,
        items: const [
          BottomNavigationBarItem(
              icon: Icon(Icons.receipt_long), label: '账单'),
          BottomNavigationBarItem(
              icon: Icon(Icons.add_circle_outline), label: '记账'),
          BottomNavigationBarItem(icon: Icon(Icons.pie_chart), label: '统计'),
        ],
      ),
    );
  }

  // ==================== 标签页 1：账单列表 ====================

  Widget _buildBillList() {
    final list = _filteredExpenses;
    final expenseTotal =
        list.where((e) => e.isExpense).fold<double>(0, (sum, e) => sum + e.amount);
    final incomeTotal =
        list.where((e) => !e.isExpense).fold<double>(0, (sum, e) => sum + e.amount);
    final balance = incomeTotal - expenseTotal;

    return Column(
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(20, 50, 20, 16),
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Colors.orange, Colors.deepOrange],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('老母记账',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                      fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              Text(_filterSummaryText(),
                  style: const TextStyle(color: Colors.white70, fontSize: 14)),
              const SizedBox(height: 4),
              Row(
                children: [
                  _buildSummaryItem(
                      '收入', '+¥${incomeTotal.toStringAsFixed(2)}', Colors.greenAccent),
                  const SizedBox(width: 16),
                  _buildSummaryItem(
                      '支出', '-¥${expenseTotal.toStringAsFixed(2)}', Colors.redAccent),
                  const SizedBox(width: 16),
                  _buildSummaryItem(
                    '结余',
                    '${balance >= 0 ? '+' : ''}¥${balance.toStringAsFixed(2)}',
                    balance >= 0 ? Colors.white : Colors.redAccent,
                    bold: true,
                  ),
                ],
              ),
            ],
          ),
        ),
        _buildFilterBar(),
        Expanded(
          child: list.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.inbox, size: 64, color: Colors.grey[300]),
                      const SizedBox(height: 12),
                      Text('还没有记录',
                          style:
                              TextStyle(fontSize: 16, color: Colors.grey[400])),
                      const SizedBox(height: 4),
                      Text('点击底部"记账"开始记录吧 ✍️',
                          style: TextStyle(
                              fontSize: 14, color: Colors.grey[350])),
                    ],
                  ),
                )
              : ListView.builder(
                  itemCount: list.length,
                  padding: const EdgeInsets.only(bottom: 16),
                  itemBuilder: (context, index) =>
                      _buildRecordItem(list[index], index),
                ),
        ),
      ],
    );
  }

  Widget _buildSummaryItem(String label, String amount, Color color,
      {bool bold = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(color: Colors.white70, fontSize: 12)),
        Text(amount,
            style: TextStyle(
                color: color,
                fontSize: bold ? 18 : 16,
                fontWeight: bold ? FontWeight.bold : FontWeight.w500)),
      ],
    );
  }

  String _filterSummaryText() {
    final parts = <String>[];
    if (_filterMonth != null) parts.add('${_filterMonth!.month}月');
    if (_filterCategory != null) parts.add(_filterCategory!);
    if (_filterType == true) {
      parts.add('仅支出');
    } else if (_filterType == false) {
      parts.add('仅收入');
    }
    if (parts.isEmpty) parts.add('全部账单');
    return '${parts.join(' · ')} 汇总';
  }

  Widget _buildFilterBar() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          SegmentedButton<bool?>(
            segments: const [
              ButtonSegment(value: null, label: Text('全部')),
              ButtonSegment(value: true, label: Text('支出')),
              ButtonSegment(value: false, label: Text('收入')),
            ],
            selected: {_filterType},
            onSelectionChanged: (vals) =>
                setState(() => _filterType = vals.first),
            style: const ButtonStyle(
              visualDensity: VisualDensity.compact,
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: DropdownButtonFormField<String?>(
              initialValue: _filterCategory,
              decoration: const InputDecoration(
                labelText: '分类',
                contentPadding:
                    EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                border: OutlineInputBorder(),
                isDense: true,
              ),
              items: [
                const DropdownMenuItem(value: null, child: Text('全部分类')),
                ...ExpenseCategory.expenseCategories.map((cat) =>
                    DropdownMenuItem(
                        value: cat.name,
                        child: Text('${cat.icon} ${cat.name}'))),
                ...ExpenseCategory.incomeCategories.map((cat) =>
                    DropdownMenuItem(
                        value: cat.name,
                        child: Text('${cat.icon} ${cat.name}'))),
              ],
              onChanged: (val) => setState(() => _filterCategory = val),
            ),
          ),
          const SizedBox(width: 6),
          SizedBox(
            width: 130,
            child: OutlinedButton.icon(
              onPressed: () async {
                final picked = await showDatePicker(
                  context: context,
                  initialDate: _filterMonth ?? DateTime.now(),
                  firstDate: DateTime(2020),
                  lastDate: DateTime.now().add(const Duration(days: 1)),
                  helpText: '选择筛选月份',
                );
                if (picked != null) {
                  setState(() =>
                      _filterMonth = DateTime(picked.year, picked.month));
                }
              },
              icon: const Icon(Icons.calendar_month, size: 16),
              label: Text(
                _filterMonth == null
                    ? '月份'
                    : '${_filterMonth!.year}/${_filterMonth!.month}',
                style: const TextStyle(fontSize: 12),
              ),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              ),
            ),
          ),
          if (_filterCategory != null ||
              _filterMonth != null ||
              _filterType != null)
            IconButton(
              onPressed: () {
                setState(() {
                  _filterCategory = null;
                  _filterMonth = null;
                  _filterType = null;
                });
              },
              icon: const Icon(Icons.clear, size: 18),
              tooltip: '清除筛选',
              visualDensity: VisualDensity.compact,
            ),
        ],
      ),
    );
  }

  Widget _buildRecordItem(Expense e, int index) {
    final isExpense = e.isExpense;
    final color = isExpense ? Colors.red : Colors.green;
    final prefix = isExpense ? '-' : '+';

    return Dismissible(
      key: ValueKey(e.id),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) => _confirmDelete(index),
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
        decoration: BoxDecoration(
          color: Colors.red,
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.delete, color: Colors.white, size: 20),
            SizedBox(width: 4),
            Text('删除', style: TextStyle(color: Colors.white, fontSize: 14)),
          ],
        ),
      ),
      child: Card(
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
        child: ListTile(
          leading: CircleAvatar(
            backgroundColor:
                isExpense ? Colors.red.shade50 : Colors.green.shade50,
            child: Text(e.category.icon, style: const TextStyle(fontSize: 22)),
          ),
          title: Row(
            children: [
              Text(e.category.name),
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                decoration: BoxDecoration(
                  color: isExpense ? Colors.red.shade50 : Colors.green.shade50,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(e.typeLabel,
                    style: TextStyle(
                        fontSize: 11,
                        color: isExpense ? Colors.red : Colors.green)),
              ),
            ],
          ),
          subtitle: Text(
            [
              _formatDate(e.date),
              if (e.note != null && e.note!.isNotEmpty) e.note!,
            ].join(' · '),
            style: TextStyle(color: Colors.grey[600], fontSize: 13),
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '$prefix¥${e.amount.toStringAsFixed(2)}',
                style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.bold,
                    color: color),
              ),
              const SizedBox(width: 4),
              IconButton(
                icon: const Icon(Icons.delete_outline, size: 20),
                color: Colors.grey[400],
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(
                    minWidth: 32, minHeight: 32),
                onPressed: () => _deleteExpense(index),
                tooltip: '删除',
              ),
            ],
          ),
          onLongPress: () => _deleteExpense(index),
        ),
      ),
    );
  }

  String _formatDate(DateTime date) {
    return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  }

  // ==================== 标签页 2：记账 ====================

  Widget _buildAddExpense() {
    return Stack(
      children: [
        SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(24, 60, 24, 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 标题栏 + 识图按钮
                Row(
                  children: [
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('记一笔 ✏️',
                              style: TextStyle(
                                  fontSize: 26, fontWeight: FontWeight.bold)),
                          SizedBox(height: 4),
                        ],
                      ),
                    ),
                    // 📷 识图按钮
                    ElevatedButton.icon(
                      onPressed:
                          _isOcrProcessing ? null : _startOcr,
                      icon: const Icon(Icons.document_scanner, size: 20),
                      label: const Text('识图'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.blue,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                  ],
                ),
                Text(
                  _isExpense ? '记录一笔支出' : '记录一笔收入',
                  style: TextStyle(fontSize: 15, color: Colors.grey[500]),
                ),
                const SizedBox(height: 24),

                // 支出/收入切换
                Row(
                  children: [
                    Expanded(
                      child: GestureDetector(
                        onTap: () => _toggleType(true),
                        child: Container(
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          decoration: BoxDecoration(
                            color: _isExpense ? Colors.red : Colors.grey[200],
                            borderRadius: const BorderRadius.only(
                                topLeft: Radius.circular(12),
                                bottomLeft: Radius.circular(12)),
                          ),
                          child: const Center(
                              child: Text('💸 支出',
                                  style: TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.bold))),
                        ),
                      ),
                    ),
                    Expanded(
                      child: GestureDetector(
                        onTap: () => _toggleType(false),
                        child: Container(
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          decoration: BoxDecoration(
                            color: !_isExpense ? Colors.green : Colors.grey[200],
                            borderRadius: const BorderRadius.only(
                                topRight: Radius.circular(12),
                                bottomRight: Radius.circular(12)),
                          ),
                          child: const Center(
                              child: Text('💰 收入',
                                  style: TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.bold))),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 28),

                // 金额
                TextField(
                  controller: _amountController,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  autofocus: true,
                  style: TextStyle(
                      fontSize: 36,
                      fontWeight: FontWeight.bold,
                      color: _isExpense ? Colors.black87 : Colors.green),
                  decoration: InputDecoration(
                    labelText: '金额',
                    prefixText: '¥ ',
                    prefixStyle: TextStyle(
                        fontSize: 36,
                        fontWeight: FontWeight.bold,
                        color: _isExpense ? Colors.black54 : Colors.green),
                    border: const UnderlineInputBorder(),
                    hintText: '0.00',
                  ),
                ),
                const SizedBox(height: 28),

                // 分类
                Text(
                  _isExpense ? '选择支出分类' : '选择收入来源',
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w500),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _currentCategories.map((cat) {
                    final selected = _selectedCategory == cat.name;
                    final activeColor = _isExpense ? Colors.red : Colors.green;
                    return GestureDetector(
                      onTap: () =>
                          setState(() => _selectedCategory = cat.name),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 14, vertical: 8),
                        decoration: BoxDecoration(
                          color: selected ? activeColor : Colors.grey[100],
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(
                            color: selected ? activeColor : Colors.grey[300]!,
                          ),
                        ),
                        child: Text('${cat.icon} ${cat.name}',
                            style: TextStyle(
                                color: selected ? Colors.white : Colors.black87,
                                fontWeight: selected
                                    ? FontWeight.bold
                                    : FontWeight.normal)),
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: 24),

                // 日期
                Row(
                  children: [
                    const Text('日期：',
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w500)),
                    TextButton.icon(
                      onPressed: () async {
                        final picked = await showDatePicker(
                          context: context,
                          initialDate: _selectedDate,
                          firstDate: DateTime(2020),
                          lastDate: DateTime.now(),
                          helpText: '选择日期',
                        );
                        if (picked != null) {
                          setState(() => _selectedDate = picked);
                        }
                      },
                      icon: const Icon(Icons.calendar_today, size: 16),
                      label: Text(_formatDate(_selectedDate)),
                    ),
                  ],
                ),
                const SizedBox(height: 16),

                // 备注
                TextField(
                  controller: _noteController,
                  decoration: const InputDecoration(
                    labelText: '备注（选填）',
                    hintText: '比如：超市买菜 / 工资到账',
                    border: OutlineInputBorder(),
                  ),
                  maxLines: 3,
                ),
                const SizedBox(height: 36),

                // 确认按钮
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton(
                    onPressed: _addExpense,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _isExpense ? Colors.red : Colors.green,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                    child: Text(
                      _isExpense ? '记一笔支出 ✅' : '记一笔收入 ✅',
                      style: const TextStyle(fontSize: 18),
                    ),
                  ),
                ),
                const SizedBox(height: 32),
              ],
            ),
          ),
        ),

        // OCR 处理中遮罩
        if (_isOcrProcessing)
          Container(
            color: Colors.black54,
            child: const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircularProgressIndicator(color: Colors.white),
                  SizedBox(height: 16),
                  Text('正在识别图片中的文字...',
                      style: TextStyle(color: Colors.white, fontSize: 16)),
                  SizedBox(height: 4),
                  Text('请稍候，大约需要 2~5 秒',
                      style: TextStyle(color: Colors.white70, fontSize: 13)),
                ],
              ),
            ),
          ),
      ],
    );
  }

  // ==================== 标签页 3：月度统计 ====================

  Widget _buildStats() {
    final allStats = _getMonthStats(_statsMonth);
    final expenseStats = allStats['expense']!;
    final incomeStats = allStats['income']!;
    final expenseTotal =
        expenseStats.values.fold<double>(0, (sum, v) => sum + v);
    final incomeTotal =
        incomeStats.values.fold<double>(0, (sum, v) => sum + v);
    final balance = incomeTotal - expenseTotal;

    final expenseEntries = expenseStats.entries
        .where((e) => e.value > 0)
        .toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final incomeEntries = incomeStats.entries
        .where((e) => e.value > 0)
        .toList()
      ..sort((a, b) => b.value.compareTo(a.value));

    final recordCount = _expenses
        .where((e) =>
            e.date.year == _statsMonth.year &&
            e.date.month == _statsMonth.month)
        .length;

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 50, 20, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('月度统计 📊',
                style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Row(
              children: [
                IconButton(
                    icon: const Icon(Icons.chevron_left),
                    onPressed: () {
                      setState(() {
                        _statsMonth =
                            DateTime(_statsMonth.year, _statsMonth.month - 1);
                      });
                    }),
                TextButton(
                  onPressed: () async {
                    final picked = await showDatePicker(
                      context: context,
                      initialDate: _statsMonth,
                      firstDate: DateTime(2020),
                      lastDate: DateTime.now(),
                      helpText: '选择统计月份',
                    );
                    if (picked != null) {
                      setState(() =>
                          _statsMonth = DateTime(picked.year, picked.month));
                    }
                  },
                  child: Text('${_statsMonth.year}年${_statsMonth.month}月',
                      style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          color: Colors.black87)),
                ),
                IconButton(
                    icon: const Icon(Icons.chevron_right),
                    onPressed: () {
                      final next =
                          DateTime(_statsMonth.year, _statsMonth.month + 1);
                      if (next.isBefore(DateTime.now()) ||
                          (next.year == DateTime.now().year &&
                              next.month == DateTime.now().month)) {
                        setState(() => _statsMonth = next);
                      }
                    }),
              ],
            ),
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Colors.orange, Colors.deepOrange],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Column(
                children: [
                  Text(
                    '${balance >= 0 ? '+' : ''}¥${balance.toStringAsFixed(2)}',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 36,
                        fontWeight: FontWeight.bold),
                  ),
                  const Text('本月结余',
                      style: TextStyle(color: Colors.white70, fontSize: 13)),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      _buildStatBadge('收入',
                          '+¥${incomeTotal.toStringAsFixed(2)}', Colors.greenAccent),
                      const SizedBox(width: 24),
                      _buildStatBadge('支出',
                          '-¥${expenseTotal.toStringAsFixed(2)}', Colors.redAccent),
                    ],
                  ),
                  if (recordCount > 0)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text('共 $recordCount 笔记录',
                          style: const TextStyle(
                              color: Colors.white60, fontSize: 12)),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            if (expenseEntries.isNotEmpty) ...[
              const Text('支出明细 📉',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              ...expenseEntries.map((entry) => _buildCategoryRow(
                  entry.key, entry.value, expenseTotal, true)),
            ],
            if (incomeEntries.isNotEmpty) ...[
              const SizedBox(height: 16),
              const Text('收入明细 📈',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              ...incomeEntries.map((entry) => _buildCategoryRow(
                  entry.key, entry.value, incomeTotal, false)),
            ],
            if (expenseEntries.isEmpty && incomeEntries.isEmpty)
              Center(
                child: Padding(
                  padding: const EdgeInsets.all(40),
                  child: Column(
                    children: [
                      Icon(Icons.inbox, size: 48, color: Colors.grey[300]),
                      const SizedBox(height: 8),
                      Text('这个月还没有记录',
                          style: TextStyle(color: Colors.grey[400])),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatBadge(String label, String amount, Color color) {
    return Column(
      children: [
        Text(amount,
            style: TextStyle(
                color: color, fontSize: 16, fontWeight: FontWeight.bold)),
        Text(label,
            style: const TextStyle(color: Colors.white70, fontSize: 12)),
      ],
    );
  }

  Widget _buildCategoryRow(
      String categoryName, double amount, double total, bool isExpense) {
    final cat = (isExpense
            ? ExpenseCategory.expenseCategories
            : ExpenseCategory.incomeCategories)
        .firstWhere((c) => c.name == categoryName);
    final percent = total > 0 ? amount / total : 0.0;
    final color = isExpense ? Colors.red : Colors.green;

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text('${cat.icon} ${cat.name}',
                  style: const TextStyle(fontSize: 15)),
              const Spacer(),
              Text('¥${amount.toStringAsFixed(2)}',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(width: 8),
              Text('${(percent * 100).toStringAsFixed(1)}%',
                  style: TextStyle(color: Colors.grey[500], fontSize: 13)),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: percent,
              minHeight: 8,
              backgroundColor: Colors.grey[200],
              valueColor: AlwaysStoppedAnimation<Color>(color.shade300),
            ),
          ),
        ],
      ),
    );
  }
}
