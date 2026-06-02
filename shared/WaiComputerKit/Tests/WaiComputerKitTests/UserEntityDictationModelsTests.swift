import XCTest
@testable import WaiComputerKit

/// Decoding tests for User, AuthResponse, Settings, Entity, Dictation, and other
/// model wrappers that aren't covered by ModelTests / ModelEdgeCaseTests / NewFieldsModelTests.
final class UserEntityDictationModelsTests: XCTestCase {

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    // MARK: - User

    func testUserDecodesWithHasPassword() throws {
        let json = """
        {"id":"u1","email":"a@example.com","created_at":"2026-05-18T10:00:00Z","has_password":false}
        """.data(using: .utf8)!
        let user = try decoder.decode(User.self, from: json)
        XCTAssertEqual(user.id, "u1")
        XCTAssertEqual(user.email, "a@example.com")
        XCTAssertFalse(user.hasPassword)
    }

    /// has_password defaults to true when absent (e.g. legacy server payloads).
    func testUserHasPasswordDefaultsTrueWhenMissing() throws {
        let json = """
        {"id":"u1","email":"a@example.com","created_at":"2026-05-18T10:00:00Z"}
        """.data(using: .utf8)!
        let user = try decoder.decode(User.self, from: json)
        XCTAssertTrue(user.hasPassword, "missing has_password should default to true")
    }

    func testUserRoundTrip() throws {
        let user = User(
            id: "u1",
            email: "a@example.com",
            createdAt: Date(timeIntervalSince1970: 1_700_000_000),
            hasPassword: false
        )
        let data = try encoder.encode(user)
        let decoded = try decoder.decode(User.self, from: data)
        XCTAssertEqual(decoded.id, user.id)
        XCTAssertEqual(decoded.email, user.email)
        XCTAssertEqual(decoded.hasPassword, user.hasPassword)
    }

    // MARK: - Auth payloads

    func testAuthResponseDecodes() throws {
        let json = """
        {"access_token":"at","refresh_token":"rt","token_type":"Bearer"}
        """.data(using: .utf8)!
        let auth = try decoder.decode(AuthResponse.self, from: json)
        XCTAssertEqual(auth.accessToken, "at")
        XCTAssertEqual(auth.refreshToken, "rt")
        XCTAssertEqual(auth.tokenType, "Bearer")
    }

    func testAuthResponseRefreshTokenOptional() throws {
        let json = """
        {"access_token":"at","token_type":"Bearer"}
        """.data(using: .utf8)!
        let auth = try decoder.decode(AuthResponse.self, from: json)
        XCTAssertNil(auth.refreshToken)
    }

    func testRefreshTokenRequestEncodes() throws {
        let req = RefreshTokenRequest(refreshToken: "rt-1")
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"refresh_token\":\"rt-1\""))
    }

    func testLogoutRequestEncodesNilRefreshToken() throws {
        let req = LogoutRequest(refreshToken: nil)
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        // nil refresh_token still appears as `"refresh_token":null` (default encoding behavior)
        // OR omitted depending on encoder settings; just ensure round-trip works.
        let decoded = try decoder.decode(LogoutRequest.self, from: data)
        XCTAssertNil(decoded.refreshToken)
        _ = json
    }

    func testLoginRequestRoundTrip() throws {
        let req = LoginRequest(email: "a@b.com", password: "secret")
        let data = try encoder.encode(req)
        let decoded = try decoder.decode(LoginRequest.self, from: data)
        XCTAssertEqual(decoded.email, "a@b.com")
        XCTAssertEqual(decoded.password, "secret")
    }

    func testRegisterRequestEncodes() throws {
        let req = RegisterRequest(email: "a@b.com", password: "pw", acceptedLegalTerms: true)
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"email\":\"a@b.com\""))
        XCTAssertTrue(json.contains("\"password\":\"pw\""))
        XCTAssertTrue(json.contains("\"accepted_legal_terms\":true"))
        XCTAssertTrue(json.contains("\"legal_terms_version\":\"2026-05-22\""))
        XCTAssertTrue(json.contains("\"legal_privacy_version\":\"2026-05-22\""))
    }

    func testMagicLinkRequest() throws {
        let req = MagicLinkRequest(email: "a@b.com", client: "macos", locale: "ru")
        let data = try encoder.encode(req)
        let decoded = try decoder.decode(MagicLinkRequest.self, from: data)
        XCTAssertEqual(decoded.email, "a@b.com")
        XCTAssertEqual(decoded.client, "macos")
        XCTAssertEqual(decoded.locale, "ru")

        let noClient = MagicLinkRequest(email: "a@b.com")
        XCTAssertNil(noClient.client)
        XCTAssertNil(noClient.locale)
    }

    func testVerifyMagicLinkRequest() throws {
        let req = VerifyMagicLinkRequest(token: "tok-xyz")
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"token\":\"tok-xyz\""))
    }

    func testChangePasswordRequestSnakeCase() throws {
        let req = ChangePasswordRequest(currentPassword: "old", newPassword: "new")
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"current_password\":\"old\""))
        XCTAssertTrue(json.contains("\"new_password\":\"new\""))
    }

    // MARK: - UserSettings

    func testUserSettingsDecodes() throws {
        let json = """
        {
          "default_language":"ru",
          "summary_language":"en",
          "summary_style":"bullet",
          "summary_instructions":"focus on actions",
          "dictation_live_stt_provider":"deepgram",
          "dictation_live_stt_model":"nova-3",
          "recording_live_stt_provider":"deepgram",
          "recording_live_stt_model":"nova-3",
          "file_stt_provider":"elevenlabs",
          "file_stt_model":"scribe_v2",
          "dictation_post_filter_enabled":true,
          "dictation_cleanup_level":"light",
          "dictation_post_filter_provider":"openai",
          "dictation_post_filter_model":"gpt-5.5"
        }
        """.data(using: .utf8)!
        let s = try decoder.decode(UserSettings.self, from: json)
        XCTAssertEqual(s.defaultLanguage, "ru")
        XCTAssertEqual(s.summaryLanguage, "en")
        XCTAssertEqual(s.summaryStyle, "bullet")
        XCTAssertEqual(s.summaryInstructions, "focus on actions")
        XCTAssertEqual(s.dictationLiveSTTProvider, "deepgram")
        XCTAssertEqual(s.dictationLiveSTTModel, "nova-3")
        XCTAssertTrue(s.dictationPostFilterEnabled)
        XCTAssertEqual(s.dictationCleanupLevel, "light")
    }

    func testUserSettingsAllowsNullSummaryInstructions() throws {
        let json = """
        {
          "default_language":"en", "summary_language":"en", "summary_style":"bullet",
          "summary_instructions":null,
          "dictation_live_stt_provider":"deepgram", "dictation_live_stt_model":"nova-3",
          "recording_live_stt_provider":"deepgram", "recording_live_stt_model":"nova-3",
          "file_stt_provider":"elevenlabs", "file_stt_model":"scribe_v2",
          "dictation_post_filter_enabled":false,
          "dictation_cleanup_level":"none",
          "dictation_post_filter_provider":"o", "dictation_post_filter_model":"m"
        }
        """.data(using: .utf8)!
        let s = try decoder.decode(UserSettings.self, from: json)
        XCTAssertNil(s.summaryInstructions)
        XCTAssertFalse(s.dictationPostFilterEnabled)
    }

    // MARK: - UpdateSettingsRequest

    func testUpdateSettingsRequestEmpty() throws {
        let req = UpdateSettingsRequest()
        let data = try encoder.encode(req)
        let decoded = try decoder.decode(UpdateSettingsRequest.self, from: data)
        XCTAssertNil(decoded.defaultLanguage)
        XCTAssertNil(decoded.dictationPostFilterEnabled)
        XCTAssertNil(decoded.dictationCleanupLevel)
    }

    func testUpdateSettingsRequestPartial() throws {
        let req = UpdateSettingsRequest(
            defaultLanguage: "de",
            dictationPostFilterEnabled: true,
            dictationCleanupLevel: "light"
        )
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"default_language\":\"de\""))
        XCTAssertTrue(json.contains("\"dictation_post_filter_enabled\":true"))
        XCTAssertTrue(json.contains("\"dictation_cleanup_level\":\"light\""))
    }

    // MARK: - TranscriptionModelOption + Options

    func testTranscriptionModelOptionIdCompositesProviderAndModel() {
        let opt = TranscriptionModelOption(
            provider: "deepgram", model: "nova-3",
            label: "Deepgram Nova-3", description: "Realtime STT"
        )
        XCTAssertEqual(opt.id, "deepgram:nova-3")
    }

    func testTranscriptionModelOptionHashable() {
        let a = TranscriptionModelOption(provider: "p", model: "m", label: "A", description: "x")
        let b = TranscriptionModelOption(provider: "p", model: "m", label: "A", description: "x")
        XCTAssertEqual(a, b)
        XCTAssertEqual(a.hashValue, b.hashValue)
    }

    func testTranscriptionOptionsDecodes() throws {
        let json = """
        {
          "dictation_live_stt": [
            {"provider":"o","model":"m1","label":"A","description":"d"}
          ],
          "recording_live_stt": [],
          "file_stt": [],
          "dictation_post_filter": []
        }
        """.data(using: .utf8)!
        let opts = try decoder.decode(TranscriptionOptions.self, from: json)
        XCTAssertEqual(opts.dictationLiveSTT.count, 1)
        XCTAssertEqual(opts.dictationLiveSTT[0].provider, "o")
        XCTAssertEqual(opts.recordingLiveSTT.count, 0)
    }

    // MARK: - Entity

    func testEntityTypeRawValues() {
        XCTAssertEqual(EntityType.person.rawValue, "person")
        XCTAssertEqual(EntityType.topic.rawValue, "topic")
        XCTAssertEqual(EntityType.project.rawValue, "project")
        XCTAssertEqual(EntityType.organization.rawValue, "organization")
    }

    func testEntityTypeAllCases() {
        XCTAssertEqual(EntityType.allCases.count, 4)
    }

    func testEntityDecodes() throws {
        let json = """
        {"id":"e1","type":"person","name":"Mik","metadata":{"role":"founder"}}
        """.data(using: .utf8)!
        let e = try decoder.decode(Entity.self, from: json)
        XCTAssertEqual(e.id, "e1")
        XCTAssertEqual(e.type, .person)
        XCTAssertEqual(e.name, "Mik")
        XCTAssertEqual(e.metadata?["role"], "founder")
    }

    func testEntityWithNoMetadata() throws {
        let json = """
        {"id":"e1","type":"topic","name":"Audio"}
        """.data(using: .utf8)!
        let e = try decoder.decode(Entity.self, from: json)
        XCTAssertNil(e.metadata)
    }

    func testEntityRelationSnakeCase() throws {
        let json = """
        {"id":"r1","target_id":"e2","target_name":"OpenAI","target_type":"organization",
         "relation_type":"works_with","context":"realtime API"}
        """.data(using: .utf8)!
        let r = try decoder.decode(EntityRelation.self, from: json)
        XCTAssertEqual(r.targetId, "e2")
        XCTAssertEqual(r.targetType, .organization)
        XCTAssertEqual(r.relationType, "works_with")
        XCTAssertEqual(r.context, "realtime API")
    }

    func testEntityDetailDecodes() throws {
        let json = """
        {"id":"e1","type":"person","name":"Mik","metadata":null,
         "relations":[{"id":"r1","target_id":"e2","target_name":"OpenAI",
                       "target_type":"organization","relation_type":null,"context":null}]}
        """.data(using: .utf8)!
        let d = try decoder.decode(EntityDetail.self, from: json)
        XCTAssertEqual(d.relations.count, 1)
        XCTAssertEqual(d.relations[0].targetName, "OpenAI")
    }

    // MARK: - Dictation DTOs

    func testDictationEntryDTORoundTrip() throws {
        let entryID = UUID()
        let dto = DictationEntryDTO(
            clientEntryID: entryID,
            rawText: "raw",
            cleanedText: "cleaned",
            durationSeconds: 1.5,
            wordCount: 3,
            occurredAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        XCTAssertEqual(dto.id, entryID)

        let data = try encoder.encode(dto)
        let decoded = try decoder.decode(DictationEntryDTO.self, from: data)
        XCTAssertEqual(decoded.clientEntryID, entryID)
        XCTAssertEqual(decoded.rawText, "raw")
        XCTAssertEqual(decoded.cleanedText, "cleaned")
        XCTAssertEqual(decoded.wordCount, 3)
    }

    func testDictationEntryDTODecodesSnakeCase() throws {
        let uuid = UUID()
        let json = """
        {"client_entry_id":"\(uuid.uuidString)","raw_text":"r","cleaned_text":null,
         "duration_seconds":2.0,"word_count":4,"occurred_at":"2026-05-18T10:00:00Z"}
        """.data(using: .utf8)!
        let dto = try decoder.decode(DictationEntryDTO.self, from: json)
        XCTAssertEqual(dto.clientEntryID, uuid)
        XCTAssertNil(dto.cleanedText)
    }

    func testCreateDictationEntryRequestUsesISOString() throws {
        let uuid = UUID()
        let req = CreateDictationEntryRequest(
            clientEntryID: uuid, rawText: "r", cleanedText: nil,
            durationSeconds: 1.0, wordCount: 2,
            occurredAt: "2026-05-18T10:00:00Z"
        )
        let data = try encoder.encode(req)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"occurred_at\":\"2026-05-18T10:00:00Z\""))
        XCTAssertTrue(json.contains("\"client_entry_id\":\"\(uuid.uuidString)\""))
    }

    func testDictionaryWordDTORoundTrip() throws {
        let uuid = UUID()
        let dto = DictionaryWordDTO(
            clientWordID: uuid,
            word: "WaiComputer",
            replacement: nil,
            occurredAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        XCTAssertEqual(dto.id, uuid)

        let data = try encoder.encode(dto)
        let decoded = try decoder.decode(DictionaryWordDTO.self, from: data)
        XCTAssertEqual(decoded.clientWordID, uuid)
        XCTAssertEqual(decoded.word, "WaiComputer")
        XCTAssertNil(decoded.replacement)
    }

    func testCreateDictionaryWordRequest() throws {
        let uuid = UUID()
        let req = CreateDictionaryWordRequest(
            clientWordID: uuid, word: "GPT",
            replacement: "gpt", occurredAt: "2026-05-18T10:00:00Z"
        )
        let data = try encoder.encode(req)
        let decoded = try decoder.decode(CreateDictionaryWordRequest.self, from: data)
        XCTAssertEqual(decoded.clientWordID, uuid)
        XCTAssertEqual(decoded.word, "GPT")
        XCTAssertEqual(decoded.replacement, "gpt")
    }
}
