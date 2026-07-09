import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

extension UTType {
    static let waiIOSInboxMove = UTType(exportedAs: "is.waiwai.computer.ios.inbox-move")
}

struct IOSInboxDragItem: Codable, Transferable, Equatable, Hashable {
    let kind: InboxSourceKind
    let id: String

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: .waiIOSInboxMove)
    }
}

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        let environment = ProcessInfo.processInfo.environment
        Group {
            if appState.isCheckingAuth {
                ProgressView("Loading…")
            } else if !appState.hasCompletedOnboarding {
                OnboardingView()
            } else if appState.isAuthenticated {
                if let recId = environment["WAICOMPUTER_RECORDING_ID"] {
                    NavigationStack {
                        RecordingDetailView(recording: screenshotRecording(for: recId))
                    }
                } else if let comparisonId = environment["WAICOMPUTER_COMPARISON_ID"] {
                    NavigationStack {
                        ComparisonDetailView(
                            apiClient: appState.getAPIClient(),
                            comparisonId: comparisonId
                        )
                    }
                } else {
                    MainTabView()
                }
            } else {
                AuthView()
            }
        }
    }

    private func screenshotRecording(for id: String) -> Recording {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            return IOSScreenshotFixtures.recording(id: id)
        }
        #endif

        return Recording(id: id, type: .meeting, createdAt: Date())
    }
}

struct MainTabView: View {
    @EnvironmentObject var languageManager: LanguageManager
    @EnvironmentObject var appState: AppState
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @AppStorage("selectedTab") private var selectedTab = 0
    @StateObject private var recordingViewModel = RecordingViewModel()
    @State private var workspaceSelection: IOSWorkspaceSection? = .inbox
    @State private var activeWaiChatId: String?
    @State private var recoveryNotice: String?
    @State private var recoveryNoticeDismissTask: Task<Void, Never>?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                IOSWorkspaceSplitView(
                    selectedSection: workspaceSelectionBinding,
                    activeWaiChatId: activeWaiChatId,
                    apiClient: appState.getAPIClient()
                )
            } else {
                compactTabs
            }
        }
        .environmentObject(recordingViewModel)
        .tint(Palette.accent)
        .overlay(alignment: .top) {
            if let recoveryNotice {
                RecordingRecoveryBanner(message: recoveryNotice) {
                    dismissRecoveryNotice()
                }
                .padding(.top, 12)
                .padding(.horizontal, 12)
            }
        }
        .onAppear {
            // Clamp into valid range. Tags: 0 Record / 1 Library / 2 Wai / 3 Settings / 4 Materials
            // (Materials shows 3rd but tags last to preserve existing persisted selections).
            if IOSWorkspaceSection(tabValue: selectedTab) == nil { selectedTab = IOSWorkspaceSection.record.compactTabValue }
            // Allow env override for screenshots
            if let tab = ProcessInfo.processInfo.environment["WAICOMPUTER_TAB"],
               let n = Int(tab),
               IOSWorkspaceSection(tabValue: n) != nil {
                selectedTab = n
                if horizontalSizeClass == .regular {
                    workspaceSelection = IOSWorkspaceSection(tabValue: n)
                }
            }
            if horizontalSizeClass == .regular,
               let screenshotSection = screenshotWorkspaceSection {
                workspaceSelection = screenshotSection
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingRecoveryNotice)) { notification in
            guard let message = notification.userInfo?["message"] as? String,
                  !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            recoveryNotice = message
            scheduleRecoveryNoticeDismiss()
        }
        // Deep-link section navigation, mirroring MacContentView.swift:496-507.
        // The target is carried as `object` to match the macOS poster contract
        // (WaiComputerMacApp.swift:207-236). iOS maps Mac-only sections to the
        // closest existing mobile surface rather than inventing a hidden route.
        .onReceive(NotificationCenter.default.publisher(for: .init("navigateTo"))) { notification in
            guard let target = notification.object as? String else { return }
            if target == "wai",
               let chatId = notification.userInfo?["chatId"] as? String,
               !chatId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                activeWaiChatId = chatId
            }
            if let section = IOSWorkspaceSection.routeTarget(target) {
                selectWorkspaceSection(section)
            }
        }
    }

    private var compactTabs: some View {
        TabView(selection: $selectedTab) {
            RecordingView()
                .tabItem {
                    Label(t("Record", "Запись"), systemImage: "mic.circle.fill")
                }
                .tag(0)

            LibraryView()
                .tabItem {
                    Label(t("Library", "Библиотека"), systemImage: "folder.fill")
                }
                .tag(1)

            // Materials shows 3rd but keeps tag(4) so existing persisted selections
            // (Wai=2, Settings=3) are NOT disrupted for users updating from build 42.
            MaterialsView(apiClient: appState.getAPIClient())
                .tabItem {
                    Label(t("Materials", "Материалы"), systemImage: "tray.full.fill")
                }
                .tag(4)

            WaiHomeView(initialChatId: activeWaiChatId)
                .tabItem {
                    Label("Wai", systemImage: "sparkles")
                }
                .tag(2)

            SettingsView()
                .tabItem {
                    Label(t("Settings", "Настройки"), systemImage: "gear")
                }
                .tag(3)
        }
    }

    private var workspaceSelectionBinding: Binding<IOSWorkspaceSection?> {
        Binding(
            get: { workspaceSelection ?? IOSWorkspaceSection(tabValue: selectedTab) ?? .record },
            set: { selectWorkspaceSection($0 ?? .record) }
        )
    }

    private func selectWorkspaceSection(_ section: IOSWorkspaceSection) {
        if horizontalSizeClass == .regular {
            workspaceSelection = section
            if let tabValue = section.tabValue {
                selectedTab = tabValue
            }
        } else {
            workspaceSelection = nil
            selectedTab = section.compactTabValue
        }
    }

    private var screenshotWorkspaceSection: IOSWorkspaceSection? {
        #if DEBUG
        guard case .screenshot(let screen) = IOSTestingMode.current else { return nil }
        switch screen {
        case .history:
            return .history
        case .dictionary:
            return .dictionary
        case .search:
            return .search
        case .comparison:
            return .comparisons
        case .materials:
            return .materials
        case .library, .detail:
            return .library
        case .settings:
            return .settings
        case .record:
            return .record
        }
        #else
        return nil
        #endif
    }

    private func dismissRecoveryNotice() {
        recoveryNoticeDismissTask?.cancel()
        recoveryNoticeDismissTask = nil
        recoveryNotice = nil
    }

    private func scheduleRecoveryNoticeDismiss() {
        recoveryNoticeDismissTask?.cancel()
        recoveryNoticeDismissTask = Task {
            try? await Task.sleep(for: .seconds(8))
            guard !Task.isCancelled else { return }
            await MainActor.run {
                recoveryNotice = nil
                recoveryNoticeDismissTask = nil
            }
        }
    }
}

enum IOSWorkspaceSection: Identifiable, Hashable {
    case inbox
    case record
    case library
    case materials
    case comparisons
    case trash
    case folder(String)
    case history
    case dictionary
    case search
    case wai
    case settings

    var id: String {
        switch self {
        case .inbox:
            return "inbox"
        case .record:
            return "record"
        case .library:
            return "library"
        case .materials:
            return "materials"
        case .comparisons:
            return "comparisons"
        case .trash:
            return "trash"
        case .folder(let folderId):
            return "folder-\(folderId)"
        case .history:
            return "history"
        case .dictionary:
            return "dictionary"
        case .search:
            return "search"
        case .wai:
            return "wai"
        case .settings:
            return "settings"
        }
    }

    var tabValue: Int? {
        switch self {
        case .record:
            return 0
        case .library:
            return 1
        case .materials:
            return 4
        case .wai:
            return 2
        case .settings:
            return 3
        case .inbox, .comparisons, .trash, .folder, .history, .dictionary, .search:
            return nil
        }
    }

    var compactTabValue: Int {
        switch self {
        case .inbox:
            return 1
        case .record:
            return 0
        case .library:
            return 1
        case .materials:
            return 4
        case .comparisons:
            return 4
        case .wai:
            return 2
        case .trash, .folder, .search:
            return 1
        case .history, .dictionary, .settings:
            return 3
        }
    }

    init?(tabValue: Int) {
        switch tabValue {
        case 0:
            self = .record
        case 1:
            self = .library
        case 2:
            self = .wai
        case 3:
            self = .settings
        case 4:
            self = .materials
        default:
            return nil
        }
    }

    static func routeTarget(_ target: String) -> IOSWorkspaceSection? {
        switch target {
        case "inbox", "allRecordings":
            return .inbox
        case "trash":
            return .trash
        case "search":
            return .search
        case "content":
            return .inbox
        case "materials":
            return .materials
        case "comparison", "comparisons":
            return .comparisons
        case "wai", "agents":
            return .wai
        case "history":
            return .history
        case "dictionary":
            return .dictionary
        case "settings":
            return .settings
        default:
            return nil
        }
    }

    func title(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .inbox:
            return OnboardingL10n.text("Inbox", "Инбокс", language: language)
        case .record:
            return OnboardingL10n.text("Record", "Запись", language: language)
        case .library:
            return OnboardingL10n.text("Library", "Библиотека", language: language)
        case .materials:
            return OnboardingL10n.text("Materials", "Материалы", language: language)
        case .comparisons:
            return OnboardingL10n.text("Comparisons", "Сравнения", language: language)
        case .trash:
            return OnboardingL10n.text("Trash", "Корзина", language: language)
        case .folder:
            return OnboardingL10n.text("Folder", "Папка", language: language)
        case .history:
            return OnboardingL10n.text("History", "История", language: language)
        case .dictionary:
            return OnboardingL10n.text("Dictionary", "Словарь", language: language)
        case .search:
            return OnboardingL10n.text("Search", "Поиск", language: language)
        case .wai:
            return "Wai"
        case .settings:
            return OnboardingL10n.text("Settings", "Настройки", language: language)
        }
    }

    var systemImage: String {
        switch self {
        case .inbox:
            return "tray.full"
        case .record:
            return "waveform"
        case .library:
            return "tray.full"
        case .materials:
            return "doc.on.doc"
        case .comparisons:
            return "tablecells"
        case .trash:
            return "trash"
        case .folder:
            return "folder"
        case .history:
            return "clock.arrow.circlepath"
        case .dictionary:
            return "book"
        case .search:
            return "magnifyingglass"
        case .wai:
            return "sparkles"
        case .settings:
            return "gearshape"
        }
    }
}

private enum IOSWorkspaceSidebarGroup: CaseIterable, Identifiable {
    case workspace
    case memory
    case dictation
    case tools

    var id: Self { self }

    var sections: [IOSWorkspaceSection] {
        switch self {
        case .workspace:
            return [.inbox, .record, .trash]
        case .memory:
            return [.library, .materials, .comparisons]
        case .dictation:
            return [.history, .dictionary]
        case .tools:
            return [.search, .wai, .settings]
        }
    }

    func title(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .workspace:
            return OnboardingL10n.text("Workspace", "Рабочее", language: language)
        case .memory:
            return OnboardingL10n.text("Memory", "Память", language: language)
        case .dictation:
            return OnboardingL10n.text("Dictation", "Диктовка", language: language)
        case .tools:
            return OnboardingL10n.text("Tools", "Инструменты", language: language)
        }
    }
}

private struct IOSWorkspaceSplitView: View {
    @EnvironmentObject private var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Binding var selectedSection: IOSWorkspaceSection?
    @StateObject private var libraryViewModel = LibraryViewModel()
    @State private var hasLoadedLibrary = false
    @State private var isShowingCreateFolderSheet = false
    @State private var newFolderName = ""
    @State private var renameFolderTarget: Folder?
    @State private var folderNameDraft = ""
    @State private var folderPendingDeletion: Folder?
    @State private var dropTargetIdentifier: String?
    let activeWaiChatId: String?
    let apiClient: APIClient

    private var currentSection: IOSWorkspaceSection {
        selectedSection ?? .record
    }

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                List {
                    IOSWorkspaceSidebarHeader()
                        .listRowInsets(EdgeInsets(
                            top: Spacing.lg,
                            leading: Spacing.md,
                            bottom: Spacing.md,
                            trailing: Spacing.md
                        ))
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)

                    ForEach(IOSWorkspaceSidebarGroup.allCases) { group in
                        Section {
                            ForEach(group.sections) { section in
                                workspaceSidebarButton(for: section)
                            }
                        } header: {
                            Text(group.title(language: languageManager.current))
                                .waiSectionHeader()
                                .padding(.leading, Spacing.xs)
                        }

                        if group == .workspace {
                            recordingFoldersSection
                        }
                    }
                }
                .listStyle(.sidebar)
                .scrollContentBackground(.hidden)
                .background(Color(uiColor: .secondarySystemGroupedBackground))

                IOSWorkspaceSidebarFooter(
                    user: appState.currentUser,
                    isSettingsSelected: currentSection == .settings,
                    onOpenSettings: { selectedSection = .settings }
                )
                    .padding(.horizontal, Spacing.lg)
                    .padding(.vertical, Spacing.md)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(uiColor: .secondarySystemGroupedBackground))
            }
            .navigationTitle("WaiComputer")
            .navigationSplitViewColumnWidth(min: 240, ideal: 280, max: 340)
        } detail: {
            ZStack(alignment: .top) {
                workspaceDetail(for: currentSection)
                    .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())

                if let error = libraryViewModel.error {
                    IOSWorkspaceErrorBanner(message: error) {
                        libraryViewModel.error = nil
                    }
                    .padding(.top, Spacing.sm)
                    .padding(.horizontal, Spacing.lg)
                }
            }
        }
        .navigationSplitViewStyle(.balanced)
        .accessibilityIdentifier("ios-workspace-split-view")
        .task {
            await loadWorkspaceLibraryIfNeeded()
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { _ in
            Task { await loadWorkspaceLibrary(force: true) }
        }
        .sheet(isPresented: $isShowingCreateFolderSheet) {
            IOSWorkspaceNewFolderSheet(name: $newFolderName) { name in
                Task { await createFolder(named: name) }
            }
            .environmentObject(languageManager)
        }
        .alert(t("Rename Folder", "Переименовать папку"), isPresented: Binding(
            get: { renameFolderTarget != nil },
            set: { if !$0 { renameFolderTarget = nil } }
        )) {
            TextField(t("Folder name", "Имя папки"), text: $folderNameDraft)
            Button(t("Save", "Сохранить")) {
                if let folder = renameFolderTarget {
                    Task { await renameFolder(folder, to: folderNameDraft) }
                }
                renameFolderTarget = nil
            }
            .disabled(folderNameDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

            Button(t("Cancel", "Отмена"), role: .cancel) {
                renameFolderTarget = nil
            }
        }
        .confirmationDialog(
            deleteFolderDialogTitle,
            isPresented: Binding(
                get: { folderPendingDeletion != nil },
                set: { if !$0 { folderPendingDeletion = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button(t("Delete Folder", "Удалить папку"), role: .destructive) {
                if let folder = folderPendingDeletion {
                    Task { await deleteFolder(folder) }
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {
                folderPendingDeletion = nil
            }
        } message: {
            Text(t(
                "Contents stay in Inbox. Only the folder is removed.",
                "Объекты останутся в Инбоксе. Удалится только папка."
            ))
        }
    }

    @ViewBuilder
    private func workspaceDetail(for section: IOSWorkspaceSection) -> some View {
        switch section {
        case .inbox:
            IOSInboxView(
                apiClient: apiClient,
                libraryViewModel: libraryViewModel,
                onStartRecording: { selectedSection = .record }
            )
        case .record:
            RecordingView()
        case .library:
            LibraryView()
        case .materials:
            MaterialsView(apiClient: apiClient)
        case .comparisons:
            ComparisonListView(apiClient: apiClient)
        case .trash:
            IOSWorkspaceTrashView(viewModel: libraryViewModel, apiClient: apiClient)
        case .folder(let folderId):
            IOSWorkspaceFolderView(
                folderId: folderId,
                viewModel: libraryViewModel,
                apiClient: apiClient,
                onStartRecording: { selectedSection = .record }
            )
            .id(folderId)
        case .history:
            DictationHistoryView()
        case .dictionary:
            DictationDictionaryView()
        case .search:
            IOSUnifiedSearchView(apiClient: apiClient)
        case .wai:
            WaiHomeView(initialChatId: activeWaiChatId)
        case .settings:
            SettingsView()
        }
    }

    @ViewBuilder
    private var recordingFoldersSection: some View {
        Section {
            Button {
                newFolderName = ""
                isShowingCreateFolderSheet = true
            } label: {
                IOSWorkspaceSidebarCommandRow(
                    title: t("New Folder", "Новая папка"),
                    systemImage: "folder.badge.plus"
                )
            }
            .buttonStyle(.plain)
            .listRowInsets(sidebarRowInsets)
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
            .disabled(libraryViewModel.isLoading)
            .accessibilityIdentifier("ios-workspace-sidebar-new-folder")

            if libraryViewModel.isLoading && libraryViewModel.folders.isEmpty {
                HStack(spacing: Spacing.sm) {
                    ProgressView()
                        .controlSize(.small)
                    Text(t("Loading Folders…", "Загружаем папки…"))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                .padding(.vertical, Spacing.sm)
                .listRowInsets(sidebarRowInsets)
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)
                .accessibilityIdentifier("ios-workspace-sidebar-folders-loading")
            }

            ForEach(libraryViewModel.folders) { folder in
                let dropKey = "folder-\(folder.id)"
                Button {
                    selectedSection = .folder(folder.id)
                } label: {
                    IOSWorkspaceFolderSidebarRow(
                        folder: folder,
                        isSelected: currentSection == .folder(folder.id),
                        isDropTargeted: dropTargetIdentifier == dropKey
                    )
                }
                .buttonStyle(.plain)
                .listRowInsets(sidebarRowInsets)
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)
                .contextMenu {
                    Button {
                        beginRenameFolder(folder)
                    } label: {
                        Label(t("Rename", "Переименовать"), systemImage: "pencil")
                    }

                    Button(role: .destructive) {
                        folderPendingDeletion = folder
                    } label: {
                        Label(t("Delete Folder", "Удалить папку"), systemImage: "trash")
                    }
                }
                .dropDestination(for: IOSInboxDragItem.self) { items, _ in
                    handleInboxDrop(items, folderId: folder.id)
                } isTargeted: { targeted in
                    updateDropTarget(dropKey, targeted: targeted)
                }
                .dropDestination(for: URL.self) { urls, _ in
                    handleFileDrop(urls, folderId: folder.id)
                } isTargeted: { targeted in
                    updateDropTarget(dropKey, targeted: targeted)
                }
                .accessibilityIdentifier("ios-workspace-sidebar-folder-\(folder.id)")
            }
        } header: {
            Text(t("Folders", "Папки"))
                .waiSectionHeader()
                .padding(.leading, Spacing.xs)
        }
    }

    private var sidebarRowInsets: EdgeInsets {
        EdgeInsets(
            top: Spacing.xs,
            leading: Spacing.md,
            bottom: Spacing.xs,
            trailing: Spacing.md
        )
    }

    @ViewBuilder
    private func workspaceSidebarButton(for section: IOSWorkspaceSection) -> some View {
        let dropKey = "section-\(section.id)"

        switch section {
        case .inbox:
            workspaceSidebarButtonBase(for: section, dropKey: dropKey)
                .dropDestination(for: IOSInboxDragItem.self) { items, _ in
                    handleInboxDrop(items, folderId: nil)
                } isTargeted: { targeted in
                    updateDropTarget(dropKey, targeted: targeted)
                }
                .dropDestination(for: URL.self) { urls, _ in
                    handleFileDrop(urls, folderId: nil)
                } isTargeted: { targeted in
                    updateDropTarget(dropKey, targeted: targeted)
                }
        case .trash:
            workspaceSidebarButtonBase(for: section, dropKey: dropKey)
                .dropDestination(for: IOSInboxDragItem.self) { items, _ in
                    handleTrashDrop(items)
                } isTargeted: { targeted in
                    updateDropTarget(dropKey, targeted: targeted)
                }
        default:
            workspaceSidebarButtonBase(for: section, dropKey: dropKey)
        }
    }

    private func workspaceSidebarButtonBase(for section: IOSWorkspaceSection, dropKey: String) -> some View {
        Button {
            selectedSection = section
        } label: {
            IOSWorkspaceSidebarRow(
                section: section,
                isSelected: currentSection == section,
                isDropTargeted: dropTargetIdentifier == dropKey
            )
        }
        .buttonStyle(.plain)
        .listRowInsets(sidebarRowInsets)
        .listRowSeparator(.hidden)
        .listRowBackground(Color.clear)
        .accessibilityIdentifier("ios-workspace-sidebar-\(section.id)")
    }

    private func loadWorkspaceLibraryIfNeeded() async {
        guard !hasLoadedLibrary else { return }
        await loadWorkspaceLibrary(force: true)
    }

    private func loadWorkspaceLibrary(force: Bool) async {
        guard force || !hasLoadedLibrary else { return }
        hasLoadedLibrary = true

        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            libraryViewModel.loadScreenshotFixtures()
            return
        }
        #endif

        await libraryViewModel.loadLibrary(apiClient: apiClient)
    }

    private func createFolder(named name: String) async {
        guard let folder = await libraryViewModel.createFolder(name: name, apiClient: apiClient) else { return }
        selectedSection = .folder(folder.id)
    }

    private func beginRenameFolder(_ folder: Folder) {
        renameFolderTarget = folder
        folderNameDraft = folder.name
    }

    private func renameFolder(_ folder: Folder, to name: String) async {
        await libraryViewModel.renameFolder(id: folder.id, name: name, apiClient: apiClient)
    }

    private func deleteFolder(_ folder: Folder) async {
        await libraryViewModel.deleteFolder(id: folder.id, apiClient: apiClient)
        let didDelete = !libraryViewModel.folders.contains { $0.id == folder.id }
        if didDelete && currentSection == .folder(folder.id) {
            selectedSection = .inbox
        }
        folderPendingDeletion = nil
    }

    private func handleInboxDrop(_ items: [IOSInboxDragItem], folderId: String?) -> Bool {
        guard !items.isEmpty else { return false }
        moveInboxDragItems(items, to: folderId)
        dropTargetIdentifier = nil
        return true
    }

    private func handleFileDrop(_ urls: [URL], folderId: String?) -> Bool {
        guard urls.count == 1, let url = urls.first else {
            libraryViewModel.error = t(
                "Drop one file at a time.",
                "Перетащите один файл за раз."
            )
            dropTargetIdentifier = nil
            return false
        }
        uploadDroppedFile(url, to: folderId)
        dropTargetIdentifier = nil
        return true
    }

    private func handleTrashDrop(_ items: [IOSInboxDragItem]) -> Bool {
        let uniqueItems = uniqueDragItems(items)
        guard !uniqueItems.isEmpty else { return false }
        guard uniqueItems.allSatisfy({ $0.kind == .recording }) else {
            libraryViewModel.error = t(
                "Only recordings can be moved to Trash.",
                "В корзину можно перемещать только записи."
            )
            dropTargetIdentifier = nil
            return false
        }

        let ids = uniqueItems.map(\.id)
        Task {
            await libraryViewModel.trashRecordings(
                ids: ids,
                language: languageManager.current,
                apiClient: apiClient
            )
        }
        dropTargetIdentifier = nil
        return true
    }

    private func uploadDroppedFile(_ url: URL, to folderId: String?) {
        Task {
            let scoped = url.startAccessingSecurityScopedResource()
            defer {
                if scoped {
                    url.stopAccessingSecurityScopedResource()
                }
            }
            do {
                _ = try await apiClient.uploadItem(fileURL: url, folderId: folderId)
                await loadWorkspaceLibrary(force: true)
            } catch {
                libraryViewModel.error = error.userFacingMessage(context: .library)
            }
        }
    }

    private func moveInboxDragItems(_ items: [IOSInboxDragItem], to folderId: String?) {
        let uniqueItems = uniqueDragItems(items)
        guard !uniqueItems.isEmpty else { return }

        Task {
            for item in uniqueItems {
                do {
                    switch item.kind {
                    case .recording:
                        _ = try await apiClient.moveRecording(id: item.id, folderId: folderId)
                    case .item:
                        _ = try await apiClient.moveItem(id: item.id, folderId: folderId)
                    case .chat:
                        _ = try await apiClient.moveCompanionChat(chatId: item.id, folderId: folderId)
                    }
                } catch {
                    libraryViewModel.error = error.userFacingMessage(context: .library)
                }
            }
            await loadWorkspaceLibrary(force: true)
        }
    }

    private func uniqueDragItems(_ items: [IOSInboxDragItem]) -> [IOSInboxDragItem] {
        var seen = Set<IOSInboxDragItem>()
        return items.filter { seen.insert($0).inserted }
    }

    private func updateDropTarget(_ key: String, targeted: Bool) {
        if targeted {
            dropTargetIdentifier = key
        } else if dropTargetIdentifier == key {
            dropTargetIdentifier = nil
        }
    }

    private var deleteFolderDialogTitle: String {
        guard let folder = folderPendingDeletion else {
            return t("Delete Folder?", "Удалить папку?")
        }
        return String(format: t("Delete folder “%@”?", "Удалить папку «%@»?"), folder.name)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSWorkspaceTrashView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @ObservedObject var viewModel: LibraryViewModel
    let apiClient: APIClient

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                content

                if let error = viewModel.error,
                   !viewModel.trashedRecordings.isEmpty {
                    IOSWorkspaceErrorBanner(message: error) {
                        viewModel.error = nil
                    }
                    .padding(.top, Spacing.sm)
                    .padding(.horizontal, Spacing.lg)
                }
            }
            .navigationTitle(t("Trash", "Корзина"))
            .navigationBarTitleDisplayMode(.large)
            .refreshable {
                #if DEBUG
                if IOSTestingMode.current.isScreenshot {
                    viewModel.loadScreenshotFixtures()
                    return
                }
                #endif

                await viewModel.loadLibrary(apiClient: apiClient)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if viewModel.isLoading && viewModel.trashedRecordings.isEmpty {
            ProgressView(t("Loading Trash…", "Загружаем корзину…"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("ios-workspace-trash-loading")
        } else if let error = viewModel.error,
                  viewModel.trashedRecordings.isEmpty {
            ContentUnavailableView {
                Label(t("Couldn't Load Trash", "Не удалось загрузить корзину"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(error)
            } actions: {
                Button(t("Try Again", "Повторить")) {
                    Task { await viewModel.loadLibrary(apiClient: apiClient) }
                }
                .buttonStyle(.borderedProminent)
                .tint(Palette.accent)
            }
            .accessibilityIdentifier("ios-workspace-trash-error")
        } else {
            TrashView(viewModel: viewModel)
                .accessibilityIdentifier("ios-workspace-trash-view")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSWorkspaceFolderView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @ObservedObject var viewModel: LibraryViewModel
    let folderId: String
    let apiClient: APIClient
    let onStartRecording: () -> Void

    init(
        folderId: String,
        viewModel: LibraryViewModel,
        apiClient: APIClient,
        onStartRecording: @escaping () -> Void
    ) {
        self.folderId = folderId
        self.viewModel = viewModel
        self.apiClient = apiClient
        self.onStartRecording = onStartRecording
    }

    var body: some View {
        if let folder = viewModel.folders.first(where: { $0.id == folderId }) {
            IOSInboxView(
                apiClient: apiClient,
                libraryViewModel: viewModel,
                folder: folder,
                onStartRecording: onStartRecording
            )
        } else {
            NavigationStack {
                if viewModel.isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .accessibilityIdentifier("ios-workspace-folder-loading")
                } else {
                    ContentUnavailableView(
                        t("Folder Not Found", "Папка не найдена"),
                        systemImage: "folder.badge.questionmark"
                    )
                    .accessibilityIdentifier("ios-workspace-folder-missing")
                }
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSWorkspaceNewFolderSheet: View {
    @Binding var name: String
    let onCreate: (String) -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @FocusState private var nameFocused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(t("Folder name", "Имя папки"), text: $name)
                        .focused($nameFocused)
                }
            }
            .navigationTitle(t("New Folder", "Новая папка"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(t("Cancel", "Отмена")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(t("Create", "Создать")) {
                        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !trimmed.isEmpty else { return }
                        onCreate(trimmed)
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear { nameFocused = true }
        }
        .presentationDetents([.medium])
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct IOSWorkspaceErrorBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Palette.recording)
            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(3)
            Spacer()
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 12, weight: .semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(Palette.textSecondary)
            .accessibilityLabel("Dismiss")
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border)
        }
        .accessibilityIdentifier("ios-workspace-error-banner")
    }
}

private struct IOSWorkspaceSidebarHeader: View {
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        HStack(spacing: Spacing.md) {
            WaiTriangleIcon(size: 34)
                .frame(width: 42, height: 42)
                .background(.thinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(Palette.border)
                }

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("WaiComputer")
                    .font(Typography.headingLarge)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                Text(OnboardingL10n.text("Second brain", "Второй мозг", language: languageManager.current))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("ios-workspace-sidebar-header")
    }
}

private struct IOSWorkspaceSidebarRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let section: IOSWorkspaceSection
    let isSelected: Bool
    let isDropTargeted: Bool

    var body: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: section.systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(isSelected ? Palette.accent : Palette.textSecondary)
                .frame(width: 28, height: 28)
                .background(isSelected ? Palette.accentSubtle : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))

            Text(section.title(language: languageManager.current))
                .font(Typography.body.weight(isSelected ? .semibold : .regular))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.sm)
        .background(backgroundStyle)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            if isSelected || isDropTargeted {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(Palette.accent.opacity(isDropTargeted ? 0.36 : 0.18))
            }
        }
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var backgroundStyle: Color {
        if isDropTargeted {
            return Palette.accent.opacity(0.18)
        }
        return isSelected ? Palette.accentSubtle : Color.clear
    }
}

private struct IOSWorkspaceSidebarCommandRow: View {
    let title: String
    let systemImage: String

    var body: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 28, height: 28)

            Text(title)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.sm)
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct IOSWorkspaceFolderSidebarRow: View {
    let folder: Folder
    let isSelected: Bool
    let isDropTargeted: Bool

    var body: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: "folder")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(isSelected ? Palette.accent : Palette.textSecondary)
                .frame(width: 28, height: 28)
                .background(isSelected ? Palette.accentSubtle : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))

            Text(folder.name)
                .font(Typography.body.weight(isSelected ? .semibold : .regular))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text("\(folder.itemCount)")
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
                .monospacedDigit()
                .frame(minWidth: 22, minHeight: 20)
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.sm)
        .background(backgroundStyle)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            if isSelected || isDropTargeted {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(Palette.accent.opacity(isDropTargeted ? 0.36 : 0.18))
            }
        }
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var backgroundStyle: Color {
        if isDropTargeted {
            return Palette.accent.opacity(0.18)
        }
        return isSelected ? Palette.accentSubtle : Color.clear
    }
}

private struct IOSWorkspaceSidebarFooter: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let user: User?
    let isSettingsSelected: Bool
    let onOpenSettings: () -> Void

    private var appVersionDisplay: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String

        switch (version?.isEmpty == false ? version : nil, build?.isEmpty == false ? build : nil) {
        case let (.some(version), .some(build)):
            return "\(version) (\(build))"
        case let (.some(version), nil):
            return version
        case let (nil, .some(build)):
            return build
        case (nil, nil):
            return "Unknown"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "person.crop.circle.fill")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 32, height: 32)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(accountTitle)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .accessibilityIdentifier("ios-workspace-account-email")

                    Text(accountStatus)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                        .lineLimit(1)
                        .accessibilityIdentifier("ios-workspace-account-status")
                }

                Spacer(minLength: 0)

                Button(action: onOpenSettings) {
                    Image(systemName: "gearshape")
                        .font(.system(size: 14, weight: .semibold))
                        .frame(width: 30, height: 30)
                }
                .buttonStyle(.plain)
                .foregroundStyle(isSettingsSelected ? Palette.accent : Palette.textSecondary)
                .background(isSettingsSelected ? Palette.accentSubtle : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .accessibilityLabel(t("Open Settings", "Открыть настройки"))
                .accessibilityIdentifier("ios-workspace-footer-settings")
            }

            Text(appVersionDisplay)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
                .lineLimit(1)
                .accessibilityIdentifier("ios-workspace-version-footer")
        }
        .padding(Spacing.sm)
        .background(Color(uiColor: .tertiarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("ios-workspace-account-footer")
    }

    private var accountTitle: String {
        guard let email = user?.email, !email.isEmpty else {
            return t("Account", "Аккаунт")
        }
        return email
    }

    private var accountStatus: String {
        if user != nil {
            return t("Signed in", "Вход выполнен")
        }
        return t("Session active", "Сессия активна")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct RecordingRecoveryBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Palette.accentSubtle)
                    .frame(width: 34, height: 34)

                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(Palette.accent)
                    .font(Typography.headingSmall)
            }
            .accessibilityHidden(true)

            Text(message)
                .font(Typography.caption)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)

            Button(action: onDismiss) {
                Image(systemName: "xmark.circle.fill")
                    .font(Typography.label)
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(Spacing.md)
        .background(Palette.accentSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        }
        .accessibilityIdentifier("recording-recovery-banner")
    }
}

#Preview {
    ContentView()
        .environmentObject(AppState())
}
