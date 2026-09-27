import {
  registerPushTokenApiV1PushRegisterPost,
  unregisterPushTokenApiV1PushUnregisterDelete,
} from "@/api/generated/push/push";

/** The push token this device registered in this run, for sign-out to withdraw. */
let registered: string | null = null;

/** Register this device's push token for the signed-in account. */
export const registerPushToken = async (token: string, platform: string): Promise<void> => {
  await registerPushTokenApiV1PushRegisterPost({ push_token: token, platform });
  registered = token;
};

/**
 * Withdraw the push token this device registered, so the account stops being
 * sent notifications here. Called on sign-out, while the credential still
 * works; nothing to do where no token was registered.
 */
export const forgetPushOnThisDevice = async (): Promise<void> => {
  const token = registered;
  registered = null;
  if (token) {
    await unregisterPushTokenApiV1PushUnregisterDelete({ push_token: token });
  }
};
