import {
  registerPushTokenApiV1PushRegisterPost,
  unregisterPushTokenApiV1PushUnregisterDelete,
} from "@/api/generated/push/push";

/** The push tokens this device registered in this run, for sign-out to withdraw. */
const registered = new Set<string>();

/** Register this device's push token for the signed-in account. */
export const registerPushToken = async (token: string, platform: string): Promise<void> => {
  await registerPushTokenApiV1PushRegisterPost({ push_token: token, platform });
  registered.add(token);
};

/**
 * Withdraw the push token this device registered, so the account stops being
 * sent notifications here. Called on sign-out, while the credential still
 * works; nothing to do where no token was registered.
 */
export const forgetPushOnThisDevice = async (): Promise<void> => {
  const tokens = [...registered];
  registered.clear();
  await Promise.all(
    tokens.map((token) => unregisterPushTokenApiV1PushUnregisterDelete({ push_token: token }))
  );
};
