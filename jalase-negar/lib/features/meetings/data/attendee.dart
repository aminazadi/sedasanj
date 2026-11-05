/// A person chosen as present in a meeting. [name] is a snapshot taken when
/// the attendee was saved, so it survives the person being deleted later.
class Attendee {
  const Attendee({required this.personId, required this.name});

  final String personId;
  final String name;

  @override
  bool operator ==(Object other) =>
      other is Attendee && other.personId == personId && other.name == name;

  @override
  int get hashCode => Object.hash(personId, name);
}
