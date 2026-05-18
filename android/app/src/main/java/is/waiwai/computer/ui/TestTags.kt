package `is`.waiwai.computer.ui

object TestTags {
    const val OnboardingPrimaryButton = "onboarding_primary_button"
    const val AuthChoiceTryGuestButton = "auth_choice_try_guest_button"
    const val GuestConfirmButton = "guest_confirm_button"
    const val RecordButton = "record_button"
    const val SettingsSignInButton = "settings_sign_in_button"
    const val SettingsDeleteAccountButton = "settings_delete_account_button"
    const val AuthEmailField = "auth_email_field"
    const val AuthPasswordField = "auth_password_field"
    const val AuthSubmitButton = "auth_submit_button"
    const val LibraryDeleteConfirmButton = "library_delete_confirm_button"
    const val SearchQueryField = "search_query_field"
    const val SearchClearButton = "search_clear_button"
    const val SearchModeHybrid = "search_mode_hybrid"
    const val SearchModeSemantic = "search_mode_semantic"
    const val SearchModeFulltext = "search_mode_fulltext"

    fun libraryItem(recordingId: String): String = "library_item_$recordingId"

    fun searchResultItem(recordingId: String, segmentId: String): String =
        "search_result_${recordingId}_$segmentId"
}
