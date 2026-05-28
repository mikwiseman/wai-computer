import Foundation
import XCTest
@testable import WaiComputerKit

final class APIClientNewEndpointsTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
    }

    private func jsonBody(from request: URLRequest) throws -> [String: Any] {
        let data: Data
        if let httpBody = request.httpBody {
            data = httpBody
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }

            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
            defer { buffer.deallocate() }

            let read = stream.read(buffer, maxLength: 4096)
            XCTAssertGreaterThan(read, 0)
            data = Data(bytes: buffer, count: read)
        } else {
            XCTFail("Expected request body")
            throw APIError.noData
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    // MARK: - Recordings

    func testStartSummaryGenerationUsesDurableEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-1/summary-generation")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 202,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "job_id": "job-1",
              "recording_id": "rec-1",
              "status": "queued",
              "stage": "queued",
              "progress_percent": 5,
              "message": "Summary generation is queued.",
              "requested_at": "2026-05-27T09:00:00Z",
              "started_at": null,
              "completed_at": null,
              "failed_at": null,
              "error_code": null,
              "error_message": null
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let state = try await client.startSummaryGeneration(recordingId: "rec-1")

        XCTAssertEqual(state.jobId, "job-1")
        XCTAssertEqual(state.recordingId, "rec-1")
        XCTAssertEqual(state.status, "queued")
        XCTAssertEqual(state.progressPercent, 5)
        XCTAssertTrue(state.isActive)
    }

    func testGetSummaryGenerationUsesDurableEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-1/summary-generation")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "job_id": "job-1",
              "recording_id": "rec-1",
              "status": "failed",
              "stage": "failed",
              "progress_percent": 100,
              "message": "Summary generation failed.",
              "requested_at": "2026-05-27T09:00:00Z",
              "started_at": "2026-05-27T09:00:02Z",
              "completed_at": null,
              "failed_at": "2026-05-27T09:00:05Z",
              "error_code": "summarization_failed",
              "error_message": "We couldn't generate the summary right now. Please try again."
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let state = try await client.getSummaryGeneration(recordingId: "rec-1")

        XCTAssertEqual(state.jobId, "job-1")
        XCTAssertEqual(state.status, "failed")
        XCTAssertEqual(state.errorCode, "summarization_failed")
        XCTAssertTrue(state.isFailed)
    }

    // MARK: - Companion

    func testPatchCompanionChatSendsRenameBody() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "PATCH")
            XCTAssertEqual(request.url?.path, "/api/companion/chats/chat-1")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["title"] as? String, "Roadmap follow-ups")
            XCTAssertNil(body["scope"] as? [String: Any])
            XCTAssertNil(body["pinned"] as? Bool)
            XCTAssertNil(body["archived"] as? Bool)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"chat-1","title":"Roadmap follow-ups","scope":null,"pinned_at":null,
             "last_message_at":null,"archived_at":null,
             "created_at":"2026-05-18T09:00:00Z","updated_at":"2026-05-18T09:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let chat = try await client.patchCompanionChat(
            chatId: "chat-1",
            title: "Roadmap follow-ups"
        )
        XCTAssertEqual(chat.title, "Roadmap follow-ups")
    }

    func testDeleteCompanionChatUsesDeleteEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/companion/chats/chat-1")
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteCompanionChat(chatId: "chat-1")
    }

    // MARK: - Billing

    func testCreateBillingCheckoutSendsExplicitTinkoffProvider() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/billing/checkout")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["plan"] as? String, "pro")
            XCTAssertEqual(body["period"] as? String, "month")
            XCTAssertEqual(body["provider"] as? String, "tinkoff")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "provider": "tinkoff",
              "checkout_url": "https://securepay.tinkoff.ru/test-checkout"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let checkout = try await client.createBillingCheckout(
            plan: "pro",
            period: "month",
            provider: "tinkoff"
        )

        XCTAssertEqual(checkout.provider, "tinkoff")
        XCTAssertEqual(checkout.checkoutUrl, "https://securepay.tinkoff.ru/test-checkout")
    }

    func testCreateBillingCheckoutSendsPromoCodeWhenProvided() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/billing/checkout")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["plan"] as? String, "pro")
            XCTAssertEqual(body["period"] as? String, "year")
            XCTAssertEqual(body["provider"] as? String, "stripe")
            XCTAssertEqual(body["promo_code"] as? String, "TESTSALE")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "provider": "stripe",
              "checkout_url": "https://checkout.stripe.test/session"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let checkout = try await client.createBillingCheckout(
            plan: "pro",
            period: "year",
            provider: "stripe",
            promoCode: "TESTSALE"
        )

        XCTAssertEqual(checkout.provider, "stripe")
        XCTAssertEqual(checkout.checkoutUrl, "https://checkout.stripe.test/session")
    }

    func testClaimBillingPromoCodeSendsCodeAndDecodesSubscription() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/billing/promo/claim")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["code"] as? String, "WAI-TEST-30")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "plan": {
                "code": "pro",
                "name": "Pro",
                "description": null,
                "usd_amount_monthly": 12,
                "usd_amount_yearly": 96,
                "rub_amount_monthly": 999,
                "rub_amount_yearly": 7999,
                "word_cap_per_week": null,
                "memory_retention_days": null,
                "features": {
                  "billing": true
                }
              },
              "status": "active",
              "provider": "promo",
              "billing_period": "month",
              "current_period_end": "2026-06-21T12:00:00Z",
              "cancel_at_period_end": true,
              "trial_end": null,
              "enforcement_enabled": true
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let subscription = try await client.claimBillingPromoCode("WAI-TEST-30")

        XCTAssertTrue(subscription.isPro)
        XCTAssertEqual(subscription.provider, "promo")
        XCTAssertTrue(subscription.cancelAtPeriodEnd)
    }

    func testGetBillingSubscriptionDecodesActiveTinkoffProStatus() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/billing/subscription")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "plan": {
                "code": "pro",
                "name": "Pro",
                "description": null,
                "usd_amount_monthly": 12,
                "usd_amount_yearly": 96,
                "rub_amount_monthly": 999,
                "rub_amount_yearly": 7999,
                "word_cap_per_week": null,
                "memory_retention_days": null,
                "features": {
                  "billing": true
                }
              },
              "status": "active",
              "provider": "tinkoff",
              "billing_period": "month",
              "current_period_end": "2026-06-21T12:00:00Z",
              "cancel_at_period_end": false,
              "trial_end": null,
              "enforcement_enabled": true
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let subscription = try await client.getBillingSubscription()

        XCTAssertTrue(subscription.isPro)
        XCTAssertEqual(subscription.status, "active")
        XCTAssertEqual(subscription.provider, "tinkoff")
        XCTAssertEqual(subscription.billingPeriod, "month")
        XCTAssertTrue(subscription.enforcementEnabled)
    }

    // MARK: - Star Recording

    func testStarRecordingSendsPostToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-42/star")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-42",
                "title":"Starred Recording",
                "type":"note",
                "starred_at":"2026-03-15T12:00:00Z",
                "created_at":"2026-03-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.starRecording(id: "rec-42")
        XCTAssertEqual(recording.id, "rec-42")
        XCTAssertEqual(recording.title, "Starred Recording")
        XCTAssertNotNil(recording.starredAt)
    }

    func testStarRecordingReturnsUpdatedRecordingWithStarredAt() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-7",
                "title":"Meeting Notes",
                "type":"meeting",
                "starred_at":"2026-03-17T08:30:00Z",
                "created_at":"2026-03-10T09:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.starRecording(id: "rec-7")
        XCTAssertEqual(recording.type, .meeting)
        XCTAssertNotNil(recording.starredAt)
    }

    // MARK: - Unstar Recording

    func testUnstarRecordingSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-42/star")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-42",
                "title":"Unstarred Recording",
                "type":"note",
                "starred_at":null,
                "created_at":"2026-03-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.unstarRecording(id: "rec-42")
        XCTAssertEqual(recording.id, "rec-42")
        XCTAssertNil(recording.starredAt)
    }

    func testUnstarRecordingClearsStarredAtField() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-99",
                "title":"Was Starred",
                "type":"reflection",
                "created_at":"2026-02-20T14:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.unstarRecording(id: "rec-99")
        XCTAssertEqual(recording.type, .reflection)
        XCTAssertNil(recording.starredAt)
    }

    // MARK: - List Starred Recordings

    func testListStarredRecordingsSendsGetWithStarredQueryParam() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("starred=true"),
                          "Expected starred=true in query, got: \(query)")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {
                    "id":"rec-1",
                    "title":"Fav 1",
                    "type":"note",
                    "starred_at":"2026-03-15T12:00:00Z",
                    "created_at":"2026-03-01T10:00:00Z"
                },
                {
                    "id":"rec-2",
                    "title":"Fav 2",
                    "type":"meeting",
                    "starred_at":"2026-03-16T09:00:00Z",
                    "created_at":"2026-03-02T11:00:00Z"
                }
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recordings = try await client.listStarredRecordings()
        XCTAssertEqual(recordings.count, 2)
        XCTAssertEqual(recordings[0].id, "rec-1")
        XCTAssertNotNil(recordings[0].starredAt)
        XCTAssertEqual(recordings[1].id, "rec-2")
        XCTAssertNotNil(recordings[1].starredAt)
    }

    func testListStarredRecordingsReturnsEmptyArrayWhenNoneStarred() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertTrue(request.url?.query?.contains("starred=true") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        let recordings = try await client.listStarredRecordings()
        XCTAssertTrue(recordings.isEmpty)
    }

    // MARK: - Pin Chat Session



    // MARK: - Unpin Chat Session



    // MARK: - Search Chat Sessions




    // MARK: - Export Chat Session




    // MARK: - Delete Action Item

    func testDeleteActionItemSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/action-items/ai-55")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteActionItem(id: "ai-55")
    }

    func testDeleteActionItemDoesNotIncludeRequestBody() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/action-items/ai-99")

            // Verify no request body is sent
            let bodyData: Data?
            if let data = request.httpBody {
                bodyData = data
            } else if let stream = request.httpBodyStream {
                stream.open()
                defer { stream.close() }
                let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
                defer { buffer.deallocate() }
                let read = stream.read(buffer, maxLength: 1024)
                bodyData = read > 0 ? Data(bytes: buffer, count: read) : nil
            } else {
                bodyData = nil
            }
            XCTAssertNil(bodyData, "DELETE action item should not send a body")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteActionItem(id: "ai-99")
    }

    func testDeleteActionItemThrowsOn404() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 404,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"detail":"Action item not found"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        do {
            try await client.deleteActionItem(id: "ai-nonexistent")
            XCTFail("Expected httpError for 404")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, _):
                XCTAssertEqual(statusCode, 404)
            default:
                XCTFail("Expected httpError(404), got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    // MARK: - User App lifecycle

    func testListAppsIncludesStatusAndVisibilityFilters() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/apps")

            let components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)
            let queryItems = components?.queryItems ?? []
            XCTAssertEqual(queryItems.first(where: { $0.name == "status" })?.value, "live")
            XCTAssertEqual(queryItems.first(where: { $0.name == "visibility" })?.value, "public")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        let apps = try await client.listApps(status: .live, visibility: .public)
        XCTAssertTrue(apps.isEmpty)
    }

    func testCreateAppSendsLifecycleFields() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/apps")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["name"] as? String, "habit-tracker")
            XCTAssertEqual(body["display_name"] as? String, "Habit Tracker")
            XCTAssertEqual(body["description"] as? String, "Tracks daily habits")
            XCTAssertEqual(body["visibility"] as? String, "unlisted")
            XCTAssertEqual((body["settings"] as? [String: Any])?["theme"] as? String, "calm")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 201,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"app-1",
                "name":"habit-tracker",
                "display_name":"Habit Tracker",
                "description":"Tracks daily habits",
                "icon":"✅",
                "template":"tracker",
                "schema_def":{"habit":"string"},
                "app_url":null,
                "settings":{"theme":"calm"},
                "status":"draft",
                "visibility":"unlisted",
                "published_at":null,
                "last_used_at":"2026-04-01T12:00:00Z",
                "sort_order":0,
                "item_count":0,
                "created_at":"2026-04-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let app = try await client.createApp(
            name: "habit-tracker",
            displayName: "Habit Tracker",
            description: "Tracks daily habits",
            icon: "✅",
            template: "tracker",
            schemaDef: ["habit": .string("string")],
            settings: ["theme": .string("calm")],
            visibility: .unlisted
        )
        XCTAssertEqual(app.status, .draft)
        XCTAssertEqual(app.visibility, .unlisted)
        XCTAssertEqual(app.description, "Tracks daily habits")
        XCTAssertNotNil(app.lastUsedAt)
    }

    func testPublishAppSendsVisibilityAndUrl() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/apps/app-9/publish")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["visibility"] as? String, "public")
            XCTAssertEqual(body["app_url"] as? String, "https://habits.wai.computer")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"app-9",
                "name":"habits",
                "display_name":"Habits",
                "description":"Daily habits",
                "icon":"✅",
                "template":"tracker",
                "schema_def":null,
                "app_url":"https://habits.wai.computer",
                "settings":null,
                "status":"live",
                "visibility":"public",
                "published_at":"2026-04-01T14:00:00Z",
                "last_used_at":"2026-04-01T14:05:00Z",
                "sort_order":0,
                "item_count":4,
                "created_at":"2026-04-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let app = try await client.publishApp(
            "app-9",
            visibility: .public,
            appUrl: "https://habits.wai.computer"
        )
        XCTAssertEqual(app.status, .live)
        XCTAssertEqual(app.visibility, .public)
        XCTAssertEqual(app.appUrl, "https://habits.wai.computer")
        XCTAssertNotNil(app.publishedAt)
    }

    // MARK: - Realtime Transcription

    func testCreateRealtimeTranscriptionSessionSendsLanguageAndChannels() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/transcription/session")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["language"] as? String, "multi")
            XCTAssertEqual(body["channels"] as? Int, 1)
            XCTAssertEqual(body["purpose"] as? String, "recording")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "provider":"deepgram",
                "token":"dg_token_123",
                "expires_in_seconds":60,
                "sample_rate":16000,
                "audio_format":"linear16",
                "language":"multi",
                "channels":1,
                "model":"nova-3",
                "websocket_url":"wss://wai.computer/api/transcription/stream",
                "auth_scheme":"bearer",
                "keep_alive_interval_seconds":4
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let config = try await client.createRealtimeTranscriptionSession(language: "multi", channels: 1)
        XCTAssertEqual(config.provider, "deepgram")
        XCTAssertEqual(config.token, "dg_token_123")
        XCTAssertEqual(config.sampleRate, 16_000)
        XCTAssertEqual(config.model, "nova-3")
        XCTAssertEqual(config.websocketURL, "wss://wai.computer/api/transcription/stream")
        XCTAssertEqual(config.authScheme, "bearer")
        XCTAssertEqual(config.keepAliveIntervalSeconds, 4)
    }

    func testCreateRealtimeTranscriptionSessionSendsDictationPurpose() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/transcription/session")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["purpose"] as? String, "dictation")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "provider":"deepgram",
                "token":"dg_token_test",
                "expires_in_seconds":60,
                "sample_rate":16000,
                "audio_format":"linear16",
                "language":"multi",
                "channels":1,
                "model":"nova-3",
                "websocket_url":"wss://wai.computer/api/transcription/stream",
                "auth_scheme":"bearer",
                "keep_alive_interval_seconds":4
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let config = try await client.createRealtimeTranscriptionSession(
            language: "multi",
            channels: 1,
            purpose: .dictation
        )
        XCTAssertEqual(config.provider, "deepgram")
        XCTAssertEqual(config.sampleRate, 16_000)
        XCTAssertEqual(config.authScheme, "bearer")
    }

    func testCreateRealtimeVoiceSessionSendsMode() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/voice/session")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["mode"] as? String, "conversation")
            XCTAssertNil(body["agent_id"])

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "provider":"elevenlabs",
                "mode":"conversation",
                "agent_id":"agent-123",
                "signed_url":"wss://api.elevenlabs.io/v1/convai/conversation?token=signed",
                "expires_in_seconds":900,
                "environment":"production",
                "branch_id":null
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let session = try await client.createRealtimeVoiceSession(mode: .conversation)
        XCTAssertEqual(session.provider, "elevenlabs")
        XCTAssertEqual(session.agentId, "agent-123")
        XCTAssertTrue(session.signedURL.contains("api.elevenlabs.io"))
    }
}
